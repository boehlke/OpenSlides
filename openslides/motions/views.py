import re
from typing import List

import jsonschema
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.http.request import QueryDict
from rest_framework import status

from ..core.config import config
from ..core.models import Tag
from ..utils.auth import has_perm, in_some_groups
from ..utils.autoupdate import inform_changed_data, inform_deleted_data
from ..utils.rest_api import (
    CreateModelMixin,
    DestroyModelMixin,
    GenericViewSet,
    ModelViewSet,
    Response,
    ReturnDict,
    UpdateModelMixin,
    ValidationError,
    detail_route,
    list_route,
)
from .access_permissions import (
    CategoryAccessPermissions,
    MotionAccessPermissions,
    MotionBlockAccessPermissions,
    MotionChangeRecommendationAccessPermissions,
    MotionCommentSectionAccessPermissions,
    StatuteParagraphAccessPermissions,
    WorkflowAccessPermissions,
)
from .exceptions import WorkflowError
from .models import (
    Category,
    Motion,
    MotionBlock,
    MotionChangeRecommendation,
    MotionComment,
    MotionCommentSection,
    MotionPoll,
    State,
    StatuteParagraph,
    Submitter,
    Workflow,
)
from .serializers import MotionPollSerializer, StateSerializer


# Viewsets for the REST API


class MotionViewSet(ModelViewSet):
    """
    API endpoint for motions.

    There are a lot of views. See check_view_permissions().
    """

    access_permissions = MotionAccessPermissions()
    queryset = Motion.objects.all()

    def check_view_permissions(self):
        """
        Returns True if the user has required permissions.
        """
        if self.action in ("list", "retrieve"):
            result = self.get_access_permissions().check_permissions(self.request.user)
        elif self.action in ("metadata", "partial_update", "update", "destroy"):
            result = has_perm(self.request.user, "motions.can_see")
            # For partial_update, update and destroy requests the rest of the check is
            # done in the update method. See below.
        elif self.action == "create":
            result = has_perm(self.request.user, "motions.can_see")
            # For create the rest of the check is done in the create method. See below.
        elif self.action in (
            "set_state",
            "manage_multiple_state",
            "set_recommendation",
            "manage_multiple_recommendation",
            "follow_recommendation",
            "manage_multiple_submitters",
            "manage_multiple_tags",
            "create_poll",
        ):
            result = has_perm(self.request.user, "motions.can_see") and has_perm(
                self.request.user, "motions.can_manage_metadata"
            )
        elif self.action in ("sort", "manage_comments"):
            result = has_perm(self.request.user, "motions.can_see") and has_perm(
                self.request.user, "motions.can_manage"
            )
        elif self.action == "support":
            result = has_perm(self.request.user, "motions.can_see") and has_perm(
                self.request.user, "motions.can_support"
            )
        else:
            result = False
        return result

    def destroy(self, request, *args, **kwargs):
        """
        Destroy is allowed if the user has manage permissions, or he is the submitter and
        the current state allows to edit the motion.
        """
        motion = self.get_object()

        if not (
            (
                has_perm(request.user, "motions.can_manage")
                or motion.is_submitter(request.user)
                and motion.state.allow_submitter_edit
            )
        ):
            self.permission_denied(request)

        result = super().destroy(request, *args, **kwargs)

        # Fire autoupdate again to save information to OpenSlides history.
        inform_deleted_data(
            [(motion.get_collection_string(), motion.pk)],
            information="Motion deleted",
            user_id=request.user.pk,
        )

        return result

    def create(self, request, *args, **kwargs):
        """
        Customized view endpoint to create a new motion.
        """
        # This is a hack to make request.data mutable. Otherwise fields can not be deleted.
        if isinstance(request.data, QueryDict):
            request.data._mutable = True

        # Check if amendment request and if parent motion exists. Check also permissions.
        if request.data.get("parent_id") is not None:
            # Amendment
            if not has_perm(self.request.user, "motions.can_create_amendments"):
                self.permission_denied(request)
            try:
                parent_motion = Motion.objects.get(pk=request.data["parent_id"])
            except Motion.DoesNotExist:
                raise ValidationError({"detail": "The parent motion does not exist."})
        else:
            # Common motion
            if not has_perm(self.request.user, "motions.can_create"):
                self.permission_denied(request)
            parent_motion = None

        # Check permission to send some data.
        if not has_perm(request.user, "motions.can_manage"):
            # Remove fields that the user is not allowed to send.
            # The list() is required because we want to use del inside the loop.
            keys = list(request.data.keys())
            whitelist = ["title", "text", "reason", "category_id"]
            if parent_motion is not None:
                # For creating amendments.
                whitelist.extend(
                    [
                        "parent_id",
                        "amendment_paragraphs",
                        "motion_block_id",  # This and the category_id will be set to the matching
                        # values from parent_motion.
                    ]
                )
                request.data["category_id"] = parent_motion.category_id
                request.data["motion_block_id"] = parent_motion.motion_block_id
            for key in keys:
                if key not in whitelist:
                    del request.data[key]

        # Validate data and create motion.
        # Attention: Even user without permission can_manage_metadata is allowed
        # to create a new motion and set such metadata like category, motion block and origin.
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        motion = serializer.save(request_user=request.user)

        # Check for submitters and make ids unique
        if isinstance(request.data, QueryDict):
            submitters_id = request.data.getlist("submitters_id")
        else:
            submitters_id = request.data.get("submitters_id")
            if submitters_id is None:
                submitters_id = []
        if not isinstance(submitters_id, list):
            raise ValidationError(
                {"detail": "If submitters_id is given, it has to be a list."}
            )

        submitters_id_unique = set()
        for id in submitters_id:
            try:
                submitters_id_unique.add(int(id))
            except ValueError:
                continue

        submitters = []
        for submitter_id in submitters_id_unique:
            try:
                submitters.append(get_user_model().objects.get(pk=submitter_id))
            except get_user_model().DoesNotExist:
                continue  # Do not add users that do not exist

        # Add the request user, if he is authenticated and no submitters were given:
        if not submitters and request.user.is_authenticated:
            submitters.append(request.user)

        # create all submitters
        for submitter in submitters:
            Submitter.objects.add(submitter, motion)

        # Write the log message and initiate response.
        motion.write_log(["Motion created"], request.user)

        # Send new submitters and supporters via autoupdate because users
        # without permission to see users may not have them but can get it now.
        new_users = list(motion.submitters.all())
        new_users.extend(motion.supporters.all())
        inform_changed_data(new_users)

        headers = self.get_success_headers(serializer.data)
        # Strip out response data so nobody gets unrestricted data.
        data = ReturnDict(id=serializer.data.get("id"), serializer=serializer)
        return Response(data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        """
        Customized view endpoint to update a motion.

        Checks also whether the requesting user can update the motion. He
        needs at least the permissions 'motions.can_see' (see
        self.check_view_permissions()). Also check manage permission or
        submitter and state.
        """
        # This is a hack to make request.data mutable. Otherwise fields can not be deleted.
        if isinstance(request.data, QueryDict):
            request.data._mutable = True

        # Get motion.
        motion = self.get_object()

        # Check permissions.
        if (
            not has_perm(request.user, "motions.can_manage")
            and not has_perm(request.user, "motions.can_manage_metadata")
            and not (
                motion.is_submitter(request.user) and motion.state.allow_submitter_edit
            )
        ):
            self.permission_denied(request)

        # Check permission to send only some data.
        # Attention: Users with motions.can_manage permission can change all
        #            fields even if they do not have motions.can_manage_metadata
        #            permission.
        if not has_perm(request.user, "motions.can_manage"):
            # Remove fields that the user is not allowed to change.
            # The list() is required because we want to use del inside the loop.
            keys = list(request.data.keys())
            whitelist: List[str] = []
            # Add title, text and reason to the whitelist only, if the user is the submitter.
            if motion.is_submitter(request.user) and motion.state.allow_submitter_edit:
                whitelist.extend(("title", "text", "reason"))

            if has_perm(request.user, "motions.can_manage_metadata"):
                whitelist.extend(
                    ("category_id", "motion_block_id", "origin", "supporters_id")
                )

            for key in keys:
                if key not in whitelist:
                    del request.data[key]

        # Validate data and update motion.
        serializer = self.get_serializer(
            motion, data=request.data, partial=kwargs.get("partial", False)
        )
        serializer.is_valid(raise_exception=True)
        updated_motion = serializer.save()

        # Write the log message, check removal of supporters and initiate response.
        # TODO: Log if a motion was updated.
        updated_motion.write_log(["Motion updated"], request.user)
        if (
            config["motions_remove_supporters"]
            and updated_motion.state.allow_support
            and not has_perm(request.user, "motions.can_manage")
        ):
            updated_motion.supporters.clear()
            updated_motion.write_log(["All supporters removed"], request.user)

        # Send new supporters via autoupdate because users
        # without permission to see users may not have them but can get it now.
        new_users = list(updated_motion.supporters.all())
        inform_changed_data(new_users)

        # Fire autoupdate again to save information to OpenSlides history.
        inform_changed_data(
            updated_motion, information="Motion updated", user_id=request.user.pk
        )

        # We do not add serializer.data to response so nobody gets unrestricted data here.
        return Response()

    @list_route(methods=["post"])
    def sort(self, request):
        """
        Sort motions. Also checks sort_parent field to prevent hierarchical loops.

        Note: This view is not tested! Maybe needs to be refactored. Add documentation
        abou the data to be send.
        """
        nodes = request.data.get("nodes", [])
        sort_parent_id = request.data.get("parent_id")
        motions = []
        with transaction.atomic():
            for index, node in enumerate(nodes):
                id = node["id"]
                motion = Motion.objects.get(pk=id)
                motion.sort_parent_id = sort_parent_id
                motion.weight = index
                motion.save(skip_autoupdate=True)
                motions.append(motion)

                # Now check consistency. TODO: Try to use less DB queries.
                motion = Motion.objects.get(pk=id)
                ancestor = motion.sort_parent
                while ancestor is not None:
                    if ancestor == motion:
                        raise ValidationError(
                            {"detail": "There must not be a hierarchical loop."}
                        )
                    ancestor = ancestor.sort_parent

        inform_changed_data(motions)
        return Response({"detail": "The motions has been sorted."})

    @detail_route(methods=["POST", "DELETE"])
    def manage_comments(self, request, pk=None):
        """
        Create, update and delete motion comments.

        Send a POST request with {'section_id': <id>, 'comment': '<comment>'}
        to create a new comment or update an existing comment.

        Send a DELETE request with just {'section_id': <id>} to delete the comment.
        For every request, the user must have read and write permission for the given field.
        """
        motion = self.get_object()

        # Get the comment section
        section_id = request.data.get("section_id")
        if not section_id or not isinstance(section_id, int):
            raise ValidationError(
                {"detail": "You have to provide a section_id of type int."}
            )

        try:
            section = MotionCommentSection.objects.get(pk=section_id)
        except MotionCommentSection.DoesNotExist:
            raise ValidationError(
                {"detail": f"A comment section with id {section_id} does not exist."}
            )

        # the request user needs to see and write to the comment section
        if not in_some_groups(
            request.user, list(section.read_groups.values_list("pk", flat=True))
        ) or not in_some_groups(
            request.user, list(section.write_groups.values_list("pk", flat=True))
        ):
            raise ValidationError(
                {
                    "detail": "You are not allowed to see or write to the comment section."
                }
            )

        if request.method == "POST":  # Create or update
            # validate comment
            comment_value = request.data.get("comment", "")
            if not isinstance(comment_value, str):
                raise ValidationError({"detail": "The comment should be a string."})

            comment, created = MotionComment.objects.get_or_create(
                motion=motion, section=section, defaults={"comment": comment_value}
            )
            if not created:
                comment.comment = comment_value
                comment.save()

            # write log
            motion.write_log([f"Comment {section.name} updated"], request.user)
            message = f"Comment {section.name} updated"
        else:  # DELETE
            try:
                comment = MotionComment.objects.get(motion=motion, section=section)
            except MotionComment.DoesNotExist:
                # Be silent about not existing comments, but do not create a log entry.
                pass
            else:
                comment.delete()

                motion.write_log([f"Comment {section.name} deleted"], request.user)
            message = f"Comment {section.name} deleted"

        return Response({"detail": message})

    @list_route(methods=["post"])
    @transaction.atomic
    def manage_multiple_submitters(self, request):
        """
        Set or reset submitters of multiple motions.

        Send POST {"motions": [... see schema ...]} to changed the submitters.
        """
        motions = request.data.get("motions")

        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Motion manage multiple submitters schema",
            "description": "An array of motion ids with the respective user ids that should be set as submitter.",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"description": "The id of the motion.", "type": "integer"},
                    "submitters": {
                        "description": "An array of user ids the should become submitters. Use an empty array to clear submitter field.",
                        "type": "array",
                        "items": {"type": "integer"},
                        "uniqueItems": True,
                    },
                },
                "required": ["id", "submitters"],
            },
            "uniqueItems": True,
        }

        # Validate request data.
        try:
            jsonschema.validate(motions, schema)
        except jsonschema.ValidationError as err:
            raise ValidationError({"detail": str(err)})

        motion_result = []
        new_submitters = []
        for item in motions:
            # Get motion.
            try:
                motion = Motion.objects.get(pk=item["id"])
            except Motion.DoesNotExist:
                raise ValidationError({"detail": f"Motion {item['id']} does not exist"})

            # Remove all submitters.
            Submitter.objects.filter(motion=motion).delete()

            # Set new submitters.
            for submitter_id in item["submitters"]:
                try:
                    submitter = get_user_model().objects.get(pk=submitter_id)
                except get_user_model().DoesNotExist:
                    raise ValidationError(
                        {"detail": f"Submitter {submitter_id} does not exist"}
                    )
                Submitter.objects.add(submitter, motion)
                new_submitters.append(submitter)

            # Finish motion.
            motion_result.append(motion)

        # Now inform all clients.
        inform_changed_data(motion_result)

        # Also send all new submitters via autoupdate because users without
        # permission to see users may not have them but can get it now.
        # TODO: Skip history.
        inform_changed_data(new_submitters)

        # Send response.
        return Response(
            {"detail": f"{len(motion_result)} motions successfully updated."}
        )

    @detail_route(methods=["post", "delete"])
    def support(self, request, pk=None):
        """
        Special view endpoint to support a motion or withdraw support
        (unsupport).

        Send POST to support and DELETE to unsupport.
        """
        # Retrieve motion and allowed actions.
        motion = self.get_object()

        # Support or unsupport motion.
        if request.method == "POST":
            # Support motion.
            if not (
                motion.state.allow_support
                and config["motions_min_supporters"] > 0
                and not motion.is_submitter(request.user)
                and not motion.is_supporter(request.user)
            ):
                raise ValidationError({"detail": "You can not support this motion."})
            motion.supporters.add(request.user)
            motion.write_log(["Motion supported"], request.user)
            # Send new supporter via autoupdate because users without permission
            # to see users may not have it but can get it now.
            inform_changed_data([request.user])
            message = "You have supported this motion successfully."
        else:
            # Unsupport motion.
            # request.method == 'DELETE'
            if not motion.state.allow_support or not motion.is_supporter(request.user):
                raise ValidationError({"detail": "You can not unsupport this motion."})
            motion.supporters.remove(request.user)
            motion.write_log(["Motion unsupported"], request.user)
            message = "You have unsupported this motion successfully."

        # Initiate response.
        return Response({"detail": message})

    @detail_route(methods=["put"])
    def set_state(self, request, pk=None):
        """
        Special view endpoint to set and reset a state of a motion.

        Send PUT {'state': <state_id>} to set and just PUT {} to reset the
        state. Only managers can use this view.
        """
        # Retrieve motion and state.
        motion = self.get_object()
        state = request.data.get("state")

        # Set or reset state.
        if state is not None:
            # Check data and set state.
            try:
                state_id = int(state)
            except ValueError:
                raise ValidationError(
                    {"detail": "Invalid data. State must be an integer."}
                )
            if state_id not in [item.id for item in motion.state.next_states.all()]:
                raise ValidationError(
                    {"detail": f"You can not set the state to {state_id}."}
                )
            motion.set_state(state_id)
        else:
            # Reset state.
            motion.reset_state()

        # Save motion.
        motion.save(
            update_fields=["state", "identifier", "identifier_number"],
            skip_autoupdate=True,
        )
        message = f"The state of the motion was set to {motion.state.name}."

        # Write the log message and initiate response.
        motion.write_log(
            message_list=[f"State set to {motion.state.name}"],
            person=request.user,
            skip_autoupdate=True,
        )
        inform_changed_data(motion, information=f"State set to {motion.state.name}.", user_id=request.user.pk)
        return Response({"detail": message})

    @list_route(methods=["post"])
    @transaction.atomic
    def manage_multiple_state(self, request):
        """
        Set or reset states of multiple motions.

        Send POST {"motions": [... see schema ...]} to changed the states.
        """
        motions = request.data.get("motions")

        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Motion manage multiple state schema",
            "description": "An array of motion ids with the respective state ids that should be set as new state.",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"description": "The id of the motion.", "type": "integer"},
                    "state": {
                        "description": "The state id the should become the new state.",
                        "type": "integer",
                        "minimum": 1,
                    },
                },
                "required": ["id", "state"],
            },
            "uniqueItems": True,
        }

        # Validate request data.
        try:
            jsonschema.validate(motions, schema)
        except jsonschema.ValidationError as err:
            raise ValidationError({"detail": str(err)})

        motion_result = []
        for item in motions:
            # Get motion.
            try:
                motion = Motion.objects.get(pk=item["id"])
            except Motion.DoesNotExist:
                raise ValidationError({"detail": f"Motion {item['id']} does not exist"})

            # Set or reset state.
            state_id = item["state"]
            valid_states = State.objects.filter(workflow=motion.workflow_id)
            if state_id not in [item.id for item in valid_states]:
                # States of different workflows are not allowed.
                raise ValidationError(
                    {"detail": f"You can not set the state to {state_id}."}
                )
            motion.set_state(state_id)

            # Save motion.
            motion.save(update_fields=["state"], skip_autoupdate=True)

            # Write the log message.
            motion.write_log(
                message_list=["State set to", " ", motion.state.name],
                person=request.user,
                skip_autoupdate=True,
            )

            # Finish motion.
            motion_result.append(motion)

        # Now inform all clients.
        inform_changed_data(motion_result)

        # Send response.
        return Response(
            {"detail": f"{len(motion_result)} motions successfully updated."}
        )

    @detail_route(methods=["put"])
    def set_recommendation(self, request, pk=None):
        """
        Special view endpoint to set a recommendation of a motion.

        Send PUT {'recommendation': <state_id>} to set and just PUT {} to
        reset the recommendation. Only managers can use this view.
        """
        # Retrieve motion and recommendation state.
        motion = self.get_object()
        recommendation_state = request.data.get("recommendation")

        # Set or reset recommendation.
        if recommendation_state is not None:
            # Check data and set recommendation.
            try:
                recommendation_state_id = int(recommendation_state)
            except ValueError:
                raise ValidationError(
                    {"detail": "Invalid data. Recommendation must be an integer."}
                )
            recommendable_states = State.objects.filter(
                workflow=motion.workflow_id, recommendation_label__isnull=False
            )
            if recommendation_state_id not in [
                item.id for item in recommendable_states
            ]:
                raise ValidationError(
                    {
                        "detail": f"You can not set the recommendation to {recommendation_state_id}."
                    }
                )
            motion.set_recommendation(recommendation_state_id)
        else:
            # Reset recommendation.
            motion.recommendation = None

        # Save motion.
        motion.save(update_fields=["recommendation"], skip_autoupdate=True)
        label = (
            motion.recommendation.recommendation_label
            if motion.recommendation
            else "None"
        )
        message = f"The recommendation of the motion was set to {label}."

        # Write the log message and initiate response.
        motion.write_log(
            message_list=["Recommendation set to", " ", label],
            person=request.user,
            skip_autoupdate=True,
        )
        inform_changed_data(motion)
        return Response({"detail": message})

    @list_route(methods=["post"])
    @transaction.atomic
    def manage_multiple_recommendation(self, request):
        """
        Set or reset recommendations of multiple motions.

        Send POST {"motions": [... see schema ...]} to changed the recommendations.
        """
        motions = request.data.get("motions")

        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Motion manage multiple recommendations schema",
            "description": "An array of motion ids with the respective state ids that should be set as recommendation.",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"description": "The id of the motion.", "type": "integer"},
                    "recommendation": {
                        "description": "The state id the should become recommendation. Use 0 to clear recommendation field.",
                        "type": "integer",
                    },
                },
                "required": ["id", "recommendation"],
            },
            "uniqueItems": True,
        }

        # Validate request data.
        try:
            jsonschema.validate(motions, schema)
        except jsonschema.ValidationError as err:
            raise ValidationError({"detail": str(err)})

        motion_result = []
        for item in motions:
            # Get motion.
            try:
                motion = Motion.objects.get(pk=item["id"])
            except Motion.DoesNotExist:
                raise ValidationError({"detail": f"Motion {item['id']} does not exist"})

            # Set or reset recommendation.
            recommendation_state_id = item["recommendation"]
            if recommendation_state_id == 0:
                # Reset recommendation.
                motion.recommendation = None
            else:
                # Check data and set recommendation.
                recommendable_states = State.objects.filter(
                    workflow=motion.workflow_id, recommendation_label__isnull=False
                )
                if recommendation_state_id not in [
                    item.id for item in recommendable_states
                ]:
                    raise ValidationError(
                        {
                            "detail": "You can not set the recommendation to {recommendation_state_id}."
                        }
                    )
                motion.set_recommendation(recommendation_state_id)

            # Save motion.
            motion.save(update_fields=["recommendation"], skip_autoupdate=True)
            label = (
                motion.recommendation.recommendation_label
                if motion.recommendation
                else "None"
            )

            # Write the log message.
            motion.write_log(
                message_list=["Recommendation set to", " ", label],
                person=request.user,
                skip_autoupdate=True,
            )

            # Finish motion.
            motion_result.append(motion)

        # Now inform all clients.
        inform_changed_data(motion_result)

        # Send response.
        return Response(
            {"detail": f"{len(motion_result)} motions successfully updated."}
        )

    @detail_route(methods=["post"])
    def follow_recommendation(self, request, pk=None):
        motion = self.get_object()
        if motion.recommendation is None:
            raise ValidationError({"detail": "Cannot set an empty recommendation."})

        # Set state.
        motion.set_state(motion.recommendation)

        # Set the special state comment.
        extension = request.data.get("state_extension")
        if extension is not None:
            motion.state_extension = extension

        # Save and write log.
        motion.save(
            update_fields=[
                "state",
                "identifier",
                "identifier_number",
                "state_extension",
            ],
            skip_autoupdate=True,
        )
        motion.write_log(
            message_list=["State set to", " ", motion.state.name],
            person=request.user,
            skip_autoupdate=True,
        )

        # Now send all changes to the clients.
        inform_changed_data(motion)
        return Response({"detail": "Recommendation followed successfully."})

    @detail_route(methods=["post"])
    def create_poll(self, request, pk=None):
        """
        View to create a poll. It is a POST request without any data.
        """
        motion = self.get_object()
        if not motion.state.allow_create_poll:
            raise ValidationError(
                {"detail": "You can not create a poll in this motion state."}
            )
        try:
            with transaction.atomic():
                poll = motion.create_poll(skip_autoupdate=True)
        except WorkflowError as err:
            raise ValidationError({"detail": err})
        motion.write_log(["Vote created"], request.user, skip_autoupdate=True)

        inform_changed_data(motion)
        return Response(
            {"detail": "Vote created successfully.", "createdPollId": poll.pk}
        )

    @list_route(methods=["post"])
    @transaction.atomic
    def manage_multiple_tags(self, request):
        """
        Set or reset tags of multiple motions.

        Send POST {"motions": [... see schema ...]} to changed the tags.
        """
        motions = request.data.get("motions")

        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Motion manage multiple tags schema",
            "description": "An array of motion ids with the respective tags ids that should be set as tag.",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"description": "The id of the motion.", "type": "integer"},
                    "tags": {
                        "description": "An array of tag ids the should become tags. Use an empty array to clear tag field.",
                        "type": "array",
                        "items": {"type": "integer"},
                        "uniqueItems": True,
                    },
                },
                "required": ["id", "tags"],
            },
            "uniqueItems": True,
        }

        # Validate request data.
        try:
            jsonschema.validate(motions, schema)
        except jsonschema.ValidationError as err:
            raise ValidationError({"detail": str(err)})

        motion_result = []
        for item in motions:
            # Get motion.
            try:
                motion = Motion.objects.get(pk=item["id"])
            except Motion.DoesNotExist:
                raise ValidationError({"detail": f"Motion {item['id']} does not exist"})

            # Set new tags
            for tag_id in item["tags"]:
                if not Tag.objects.filter(pk=tag_id).exists():
                    raise ValidationError({"detail": f"Tag {tag_id} does not exist"})
            motion.tags.set(item["tags"])

            # Finish motion.
            motion_result.append(motion)

        # Now inform all clients.
        inform_changed_data(motion_result)

        # Send response.
        return Response(
            {"detail": f"{len(motion_result)} motions successfully updated."}
        )


class MotionPollViewSet(UpdateModelMixin, DestroyModelMixin, GenericViewSet):
    """
    API endpoint for motion polls.

    There are the following views: update, partial_update and destroy.
    """

    queryset = MotionPoll.objects.all()
    serializer_class = MotionPollSerializer

    def check_view_permissions(self):
        """
        Returns True if the user has required permissions.
        """
        return has_perm(self.request.user, "motions.can_see") and has_perm(
            self.request.user, "motions.can_manage_metadata"
        )

    def update(self, *args, **kwargs):
        """
        Customized view endpoint to update a motion poll.
        """
        response = super().update(*args, **kwargs)
        poll = self.get_object()
        poll.motion.write_log(["Vote updated"], self.request.user)
        return response

    def destroy(self, *args, **kwargs):
        """
        Customized view endpoint to delete a motion poll.
        """
        poll = self.get_object()
        result = super().destroy(*args, **kwargs)
        poll.motion.write_log(["Vote deleted"], self.request.user)
        return result


class MotionChangeRecommendationViewSet(ModelViewSet):
    """
    API endpoint for motion change recommendations.

    There are the following views: metadata, list, retrieve, create,
    partial_update, update and destroy.
    """

    access_permissions = MotionChangeRecommendationAccessPermissions()
    queryset = MotionChangeRecommendation.objects.all()

    def check_view_permissions(self):
        """
        Returns True if the user has required permissions.
        """
        if self.action in ("list", "retrieve"):
            result = self.get_access_permissions().check_permissions(self.request.user)
        elif self.action == "metadata":
            result = has_perm(self.request.user, "motions.can_see")
        elif self.action in ("create", "destroy", "partial_update", "update"):
            result = has_perm(self.request.user, "motions.can_see") and has_perm(
                self.request.user, "motions.can_manage"
            )
        else:
            result = False
        return result

    def create(self, request, *args, **kwargs):
        """
        Creating a Change Recommendation, custom exception handling
        """
        try:
            return super().create(request, *args, **kwargs)
        except DjangoValidationError as err:
            return Response({"detail": err.message}, status=400)


class MotionCommentSectionViewSet(ModelViewSet):
    """
    API endpoint for motion comment fields.
    """

    access_permissions = MotionCommentSectionAccessPermissions()
    queryset = MotionCommentSection.objects.all()

    def check_view_permissions(self):
        """
        Returns True if the user has required permissions.
        """
        if self.action in ("list", "retrieve"):
            result = self.get_access_permissions().check_permissions(self.request.user)
        elif self.action in ("create", "destroy", "update", "partial_update"):
            result = has_perm(self.request.user, "motions.can_see") and has_perm(
                self.request.user, "motions.can_manage"
            )
        else:
            result = False
        return result

    def destroy(self, *args, **kwargs):
        """
        Customized view endpoint to delete a motion comment section. Will return
        an error for the user, if still comments for this section exist.
        """
        try:
            result = super().destroy(*args, **kwargs)
        except ProtectedError as err:
            # The protected objects can just be motion comments.
            motions = [f'"{comment.motion}"' for comment in err.protected_objects.all()]
            count = len(motions)
            motions_verbose = ", ".join(motions[:3])
            if count > 3:
                motions_verbose += ", ..."

            if count == 1:
                msg = f"This section has still comments in motion {motions_verbose}."
            else:
                msg = f"This section has still comments in motions {motions_verbose}."

            msg += " " + "Please remove all comments before deletion."
            raise ValidationError({"detail": msg})
        return result


class StatuteParagraphViewSet(ModelViewSet):
    """
    API endpoint for statute paragraphs.

    There are the following views: list, retrieve, create,
    partial_update, update and destroy.
    """

    access_permissions = StatuteParagraphAccessPermissions()
    queryset = StatuteParagraph.objects.all()

    def check_view_permissions(self):
        """
        Returns True if the user has required permissions.
        """
        if self.action in ("list", "retrieve"):
            result = self.get_access_permissions().check_permissions(self.request.user)
        elif self.action in ("create", "partial_update", "update", "destroy"):
            result = has_perm(self.request.user, "motions.can_see") and has_perm(
                self.request.user, "motions.can_manage"
            )
        else:
            result = False
        return result


class CategoryViewSet(ModelViewSet):
    """
    API endpoint for categories.

    There are the following views: metadata, list, retrieve, create,
    partial_update, update, destroy and numbering.
    """

    access_permissions = CategoryAccessPermissions()
    queryset = Category.objects.all()

    def check_view_permissions(self):
        """
        Returns True if the user has required permissions.
        """
        if self.action in ("list", "retrieve"):
            result = self.get_access_permissions().check_permissions(self.request.user)
        elif self.action == "metadata":
            result = has_perm(self.request.user, "motions.can_see")
        elif self.action in (
            "create",
            "partial_update",
            "update",
            "destroy",
            "numbering",
        ):
            result = has_perm(self.request.user, "motions.can_see") and has_perm(
                self.request.user, "motions.can_manage"
            )
        else:
            result = False
        return result

    @detail_route(methods=["post"])
    def numbering(self, request, pk=None):
        """
        Special view endpoint to number all motions in this category.

        Only managers can use this view.

        Send POST {'motions': [<list of motion ids>]} to sort the given
        motions in a special order. Ids of motions which do not belong to
        the category are just ignored. Send just POST {} to sort all
        motions in the category by database id.

        Amendments will get a new identifier prefix if the old prefix matches
        the old parent motion identifier.
        """
        category = self.get_object()
        number = 0
        instances = []

        # If MOTION_IDENTIFIER_WITHOUT_BLANKS is set, don't use blanks when building identifier.
        without_blank = (
            hasattr(settings, "MOTION_IDENTIFIER_WITHOUT_BLANKS")
            and settings.MOTION_IDENTIFIER_WITHOUT_BLANKS
        )

        # Prepare ordered list of motions.
        if not category.prefix:
            prefix = ""
        elif without_blank:
            prefix = category.prefix
        else:
            prefix = f"{category.prefix} "
        motions = category.motion_set.all()
        motion_list = request.data.get("motions")
        if motion_list:
            motion_dict = {}
            for motion in motions.filter(id__in=motion_list):
                motion_dict[motion.pk] = motion
            motions = [motion_dict[pk] for pk in motion_list]

        # Change identifiers.
        error_message = None
        try:
            with transaction.atomic():
                # Collect old and new identifiers.
                motions_to_be_sorted = []
                for motion in motions:
                    if motion.is_amendment():
                        parent_identifier = motion.parent.identifier or ""
                        if without_blank:
                            prefix = f"{parent_identifier}{config['motions_amendments_prefix']}"
                        else:
                            prefix = f"{parent_identifier} {config['motions_amendments_prefix']} "
                    number += 1
                    new_identifier = (
                        f"{prefix}{motion.extend_identifier_number(number)}"
                    )
                    motions_to_be_sorted.append(
                        {
                            "motion": motion,
                            "old_identifier": motion.identifier,
                            "new_identifier": new_identifier,
                            "number": number,
                        }
                    )

                # Remove old identifiers
                for motion in motions:
                    motion.identifier = None
                    # This line is to skip agenda item autoupdate. See agenda/signals.py.
                    motion.agenda_item_update_information["skip_autoupdate"] = True
                    motion.save(skip_autoupdate=True)

                # Set new identifers and change identifiers of amendments.
                for obj in motions_to_be_sorted:
                    if Motion.objects.filter(identifier=obj["new_identifier"]).exists():
                        # Set the error message and let the code run into an IntegrityError
                        new_identifier = obj["new_identifier"]
                        error_message = (
                            f'Numbering aborted because the motion identifier "{new_identifier}" '
                            "already exists outside of this category."
                        )
                    motion = obj["motion"]
                    motion.identifier = obj["new_identifier"]
                    motion.identifier_number = obj["number"]
                    motion.save(skip_autoupdate=True)
                    instances.append(motion)
                    instances.append(motion.agenda_item)
                    # Change identifiers of amendments.
                    for child in motion.get_amendments_deep():
                        if child.identifier and child.identifier.startswith(
                            obj["old_identifier"]
                        ):
                            child.identifier = re.sub(
                                obj["old_identifier"],
                                obj["new_identifier"],
                                child.identifier,
                                count=1,
                            )
                            # This line is to skip agenda item autoupdate. See agenda/signals.py.
                            child.agenda_item_update_information[
                                "skip_autoupdate"
                            ] = True
                            child.save(skip_autoupdate=True)
                            instances.append(child)
                            instances.append(child.agenda_item)
        except IntegrityError:
            if error_message is None:
                error_message = "Error: At least one identifier of this category does already exist in another category."
            response = Response({"detail": error_message}, status=400)
        else:
            inform_changed_data(instances)
            message = f"All motions in category {category} numbered " "successfully."
            response = Response({"detail": message})
        return response


class MotionBlockViewSet(ModelViewSet):
    """
    API endpoint for motion blocks.

    There are the following views: metadata, list, retrieve, create,
    partial_update, update and destroy.
    """

    access_permissions = MotionBlockAccessPermissions()
    queryset = MotionBlock.objects.all()

    def check_view_permissions(self):
        """
        Returns True if the user has required permissions.
        """
        if self.action in ("list", "retrieve"):
            result = self.get_access_permissions().check_permissions(self.request.user)
        elif self.action == "metadata":
            result = has_perm(self.request.user, "motions.can_see")
        elif self.action in (
            "create",
            "partial_update",
            "update",
            "destroy",
            "follow_recommendations",
        ):
            result = has_perm(self.request.user, "motions.can_see") and has_perm(
                self.request.user, "motions.can_manage"
            )
        else:
            result = False
        return result

    @detail_route(methods=["post"])
    def follow_recommendations(self, request, pk=None):
        """
        View to set the states of all motions of this motion block each to
        its recommendation. It is a POST request without any data.
        """
        motion_block = self.get_object()
        instances = []
        with transaction.atomic():
            for motion in motion_block.motion_set.all():
                # Follow recommendation.
                motion.follow_recommendation()
                motion.save(skip_autoupdate=True)
                # Write the log message.
                motion.write_log(
                    message_list=["State set to", " ", motion.state.name],
                    person=request.user,
                    skip_autoupdate=True,
                )
                instances.append(motion)
        inform_changed_data(instances)
        return Response({"detail": "Followed recommendations successfully."})


class ProtectedErrorMessageMixin:
    def getProtectedErrorMessage(self, name, error):
        # The protected objects can just be motions..
        motions = ['"' + str(m) + '"' for m in error.protected_objects.all()]
        count = len(motions)
        motions_verbose = ", ".join(motions[:3])
        if count > 3:
            motions_verbose += ", ..."

        if count == 1:
            msg = f"This {name} is assigned to motion {motions_verbose}."
        else:
            msg = f"This {name} is assigned to motions {motions_verbose}."
        return f"{msg} Please remove all assignments before deletion."


class WorkflowViewSet(ModelViewSet, ProtectedErrorMessageMixin):
    """
    API endpoint for workflows.

    There are the following views: metadata, list, retrieve, create,
    partial_update, update and destroy.
    """

    access_permissions = WorkflowAccessPermissions()
    queryset = Workflow.objects.all()

    def check_view_permissions(self):
        """
        Returns True if the user has required permissions.
        """
        if self.action in ("list", "retrieve"):
            result = self.get_access_permissions().check_permissions(self.request.user)
        elif self.action == "metadata":
            result = has_perm(self.request.user, "motions.can_see")
        elif self.action in ("create", "partial_update", "update", "destroy"):
            result = has_perm(self.request.user, "motions.can_see") and has_perm(
                self.request.user, "motions.can_manage"
            )
        else:
            result = False
        return result

    def destroy(self, *args, **kwargs):
        """
        Customized view endpoint to delete a workflow.
        """
        try:
            result = super().destroy(*args, **kwargs)
        except ProtectedError as err:
            msg = self.getProtectedErrorMessage("workflow", err)
            raise ValidationError({"detail": msg})
        return result


class StateViewSet(
    CreateModelMixin,
    UpdateModelMixin,
    DestroyModelMixin,
    GenericViewSet,
    ProtectedErrorMessageMixin,
):
    """
    API endpoint for workflow states.

    There are the following views: create, update, partial_update and destroy.
    """

    queryset = State.objects.all()
    serializer_class = StateSerializer

    def check_view_permissions(self):
        """
        Returns True if the user has required permissions.
        """
        return has_perm(self.request.user, "motions.can_see") and has_perm(
            self.request.user, "motions.can_manage"
        )

    def destroy(self, *args, **kwargs):
        """
        Customized view endpoint to delete a state.
        """
        state = self.get_object()
        if (
            state.workflow.first_state.pk == state.pk
        ):  # is this the first state of the workflow?
            raise ValidationError(
                {"detail": "You cannot delete the first state of the workflow."}
            )
        try:
            result = super().destroy(*args, **kwargs)
        except ProtectedError as err:
            msg = self.getProtectedErrorMessage("workflow", err)
            raise ValidationError({"detail": msg})
        return result
