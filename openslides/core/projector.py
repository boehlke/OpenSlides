from typing import Any, Dict

from ..utils.projector import register_projector_element


# Important: All functions have to be prune. This means, that thay can only
#            access the data, that they get as argument and do not have any
#            side effects. They are called from an async context. So they have
#            to be fast!


def countdown(
    element: Dict[str, Any], all_data: Dict[str, Dict[int, Dict[str, Any]]]
) -> Dict[str, Any]:
    """
    Countdown slide.

    Returns the full_data of the countdown element.

    element = {
        name: 'core/countdown',
        id: 5,  # Countdown ID
    }
    """
    countdown_id = element.get("id") or 1

    try:
        return all_data["core/countdown"][countdown_id]
    except KeyError:
        return {"error": f"Countdown {countdown_id} does not exist"}


def message(
    element: Dict[str, Any], all_data: Dict[str, Dict[int, Dict[str, Any]]]
) -> Dict[str, Any]:
    """
    Message slide.

    Returns the full_data of the message element.

    element = {
        name: 'core/projector-message',
        id: 5,  # ProjectorMessage ID
    }
    """
    message_id = element.get("id") or 1

    try:
        return all_data["core/projector-message"][message_id]
    except KeyError:
        return {"error": f"Message {message_id} does not exist"}


def register_projector_elements() -> None:
    register_projector_element("core/countdown", countdown)
    register_projector_element("core/projector-message", message)
    # TODO: Add clock slide
