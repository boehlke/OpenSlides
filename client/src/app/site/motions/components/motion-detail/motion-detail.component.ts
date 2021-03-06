import { Component, OnInit, ViewChild } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { DomSanitizer, SafeHtml, Title } from '@angular/platform-browser';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { MatDialog, MatExpansionPanel, MatSnackBar, MatCheckboxChange } from '@angular/material';
import { take, takeWhile, multicast, skipWhile } from 'rxjs/operators';

import { Category } from '../../../../shared/models/motions/category';
import { ViewportService } from '../../../../core/services/viewport.service';
import { MotionRepositoryService } from '../../services/motion-repository.service';
import { ChangeRecoMode, LineNumberingMode, ViewMotion } from '../../models/view-motion';
import { User } from '../../../../shared/models/users/user';
import { DataStoreService } from '../../../../core/services/data-store.service';
import { TranslateService } from '@ngx-translate/core';
import { Motion } from '../../../../shared/models/motions/motion';
import { BehaviorSubject, Subscription, ReplaySubject, concat } from 'rxjs';
import { DiffLinesInParagraph, LineRange } from '../../services/diff.service';
import {
    MotionChangeRecommendationComponent,
    MotionChangeRecommendationComponentData
} from '../motion-change-recommendation/motion-change-recommendation.component';
import { ChangeRecommendationRepositoryService } from '../../services/change-recommendation-repository.service';
import { ViewChangeReco } from '../../models/view-change-reco';

import { ViewUnifiedChange } from '../../models/view-unified-change';
import { OperatorService } from '../../../../core/services/operator.service';
import { BaseViewComponent } from '../../../base/base-view';
import { ViewStatuteParagraph } from '../../models/view-statute-paragraph';
import { StatuteParagraphRepositoryService } from '../../services/statute-paragraph-repository.service';
import { ConfigService } from '../../../../core/services/config.service';
import { Workflow } from 'app/shared/models/motions/workflow';
import { LocalPermissionsService } from '../../services/local-permissions.service';
import { ViewCreateMotion } from '../../models/view-create-motion';
import { CreateMotion } from '../../models/create-motion';
import { MotionBlock } from 'app/shared/models/motions/motion-block';
import { itemVisibilityChoices, Item } from 'app/shared/models/agenda/item';
import { PromptService } from 'app/core/services/prompt.service';
import { AgendaRepositoryService } from 'app/site/agenda/services/agenda-repository.service';
import { Mediafile } from 'app/shared/models/mediafiles/mediafile';
import { MotionPdfExportService } from '../../services/motion-pdf-export.service';
import { PersonalNoteService } from '../../services/personal-note.service';
import { PersonalNoteContent } from 'app/shared/models/users/personal-note';

/**
 * Component for the motion detail view
 */
@Component({
    selector: 'os-motion-detail',
    templateUrl: './motion-detail.component.html',
    styleUrls: ['./motion-detail.component.scss']
})
export class MotionDetailComponent extends BaseViewComponent implements OnInit {
    /**
     * MatExpansionPanel for the meta info
     * Only relevant in mobile view
     */
    @ViewChild('metaInfoPanel')
    public metaInfoPanel: MatExpansionPanel;

    /**
     * MatExpansionPanel for the content panel
     * Only relevant in mobile view
     */
    @ViewChild('contentPanel')
    public contentPanel: MatExpansionPanel;

    /**
     * Motion content. Can be a new version
     */
    public contentForm: FormGroup;

    /**
     * Determine if the motion is edited
     */
    public editMotion = false;

    /**
     * Determine if the motion is new
     */
    public newMotion = false;

    /**
     * Toggle to expand/hide the motion log.
     */
    public motionLogExpanded = false;

    /**
     * Sets the motions, e.g. via an autoupdate. Reload important things here:
     * - Reload the recommendation. Not changed with autoupdates, but if the motion is loaded this needs to run.
     */
    public set motion(value: ViewMotion) {
        this._motion = value;
        this.setupRecommender();
    }

    /**
     * Returns the target motion. Might be the new one or old.
     */
    public get motion(): ViewMotion {
        return this._motion;
    }

    /**
     * @returns treu if the motion log is present and the user is allowed to see it
     */
    public get canShowLog(): boolean {
        if (
            this.motion &&
            !this.editMotion &&
            this.motion.motion.log_messages &&
            this.motion.motion.log_messages.length
        ) {
            return true;
        }
        return false;
    }

    /**
     * Saves the target motion. Accessed via the getter and setter.
     */
    private _motion: ViewMotion;

    /**
     * Value of the config variable `motions_statutes_enabled` - are statutes enabled?
     * @TODO replace by direct access to config variable, once it's available from the templates
     */
    public statutesEnabled: boolean;

    /**
     * Value of the config variable `motions_min_supporters`
     */
    public minSupporters: number;

    /**
     * Value of the config variable `motions_preamble`
     */
    public preamble: string;

    /**
     * Value of the configuration variable `motions_amendments_enabled` - are amendments enabled?
     * @TODO replace by direct access to config variable, once it's available from the templates
     */
    public amendmentsEnabled: boolean;

    /**
     * Copy of the motion that the user might edit
     */
    public motionCopy: ViewMotion;

    /**
     * All change recommendations to this motion
     */
    public changeRecommendations: ViewChangeReco[];

    /**
     * All amendments to this motions
     */
    public amendments: ViewMotion[];

    /**
     * All change recommendations AND amendments, sorted by line number.
     */
    public allChangingObjects: ViewUnifiedChange[];

    /**
     * Holds all motions. Required to navigate back and forth
     */
    public allMotions: ViewMotion[];

    /**
     * preload the next motion for direct navigation
     */
    public nextMotion: ViewMotion;

    /**
     * preload the previous motion for direct navigation
     */
    public previousMotion: ViewMotion;

    /**
     * statute paragraphs, necessary for amendments
     */
    public statuteParagraphs: ViewStatuteParagraph[] = [];

    /**
     * Subject for the Categories
     */
    public categoryObserver: BehaviorSubject<Category[]>;

    /**
     * Subject for the Categories
     */
    public workflowObserver: BehaviorSubject<Workflow[]>;

    /**
     * Subject for the Submitters
     */
    public submitterObserver: BehaviorSubject<User[]>;

    /**
     * Subject for the Supporters
     */
    public supporterObserver: BehaviorSubject<User[]>;

    /**
     * Subject for the motion blocks
     */
    public blockObserver: BehaviorSubject<MotionBlock[]>;

    /**
     * Subject for mediafiles
     */
    public mediafilesObserver: BehaviorSubject<Mediafile[]>;

    /**
     * Subject for agenda items
     */
    public agendaItemObserver: BehaviorSubject<Item[]>;

    /**
     * Determine if the name of supporters are visible
     */
    public showSupporters = false;

    /**
     * Value for os-motion-detail-diff: when this is set, that component scrolls to the given change
     */
    public scrollToChange: ViewUnifiedChange = null;

    /**
     * Custom recommender as set in the settings
     */
    public recommender: string;

    /**
     * The subscription to the recommender config variable.
     */
    private recommenderSubscription: Subscription;

    /**
     * If this is a paragraph-based amendment, this indicates if the non-affected paragraphs should be shown as well
     */
    public showAmendmentContext = false;

    /**
     * Determines the default agenda item visibility
     */
    public defaultVisibility: number;

    /**
     * Determine visibility states for the agenda that will be created implicitly
     */
    public itemVisibility = itemVisibilityChoices;

    /**
     * For using the enum constants from the template
     */
    public ChangeRecoMode = ChangeRecoMode;

    /**
     * For using the enum constants from the template
     */
    public LineNumberingMode = LineNumberingMode;

    /**
     * Indicates the LineNumberingMode Mode.
     */
    public lnMode: LineNumberingMode;

    /**
     * Indicates the Change reco Mode.
     */
    public crMode: ChangeRecoMode;

    /**
     * Indicates the maximum line length as defined in the configuration.
     */
    public lineLength: number;

    /**
     * Indicates the currently highlighted line, if any.
     */
    public highlightedLine: number;

    /**
     * The personal notes' content for this motion
     */
    public personalNoteContent: PersonalNoteContent;

    /**
     * Constuct the detail view.
     *
     * @param title
     * @param translate
     * @param matSnackBar
     * @param vp the viewport service
     * @param op Operator Service
     * @param router to navigate back to the motion list and to an existing motion
     * @param route determine if this is a new or an existing motion
     * @param formBuilder For reactive forms. Form Group and Form Control
     * @param dialogService For opening dialogs
     * @param repo Motion Repository
     * @param agendaRepo Read out agenda variables
     * @param changeRecoRepo Change Recommendation Repository
     * @param statuteRepo: Statute Paragraph Repository
     * @param DS The DataStoreService
     * @param configService The configuration provider
     * @param sanitizer For making HTML SafeHTML
     * @param promptService ensure safe deletion
     * @param pdfExport export the motion to pdf
     * @param personalNoteService: personal comments and favorite marker
     */
    public constructor(
        title: Title,
        translate: TranslateService,
        matSnackBar: MatSnackBar,
        public vp: ViewportService,
        public perms: LocalPermissionsService,
        private op: OperatorService,
        private router: Router,
        private route: ActivatedRoute,
        private formBuilder: FormBuilder,
        private dialogService: MatDialog,
        private repo: MotionRepositoryService,
        private agendaRepo: AgendaRepositoryService,
        private changeRecoRepo: ChangeRecommendationRepositoryService,
        private statuteRepo: StatuteParagraphRepositoryService,
        private DS: DataStoreService,
        private configService: ConfigService,
        private sanitizer: DomSanitizer,
        private promptService: PromptService,
        private pdfExport: MotionPdfExportService,
        private personalNoteService: PersonalNoteService
    ) {
        super(title, translate, matSnackBar);

        // Initial Filling of the Subjects
        this.submitterObserver = new BehaviorSubject(DS.getAll(User));
        this.supporterObserver = new BehaviorSubject(DS.getAll(User));
        this.categoryObserver = new BehaviorSubject(DS.getAll(Category));
        this.workflowObserver = new BehaviorSubject(DS.getAll(Workflow));
        this.blockObserver = new BehaviorSubject(DS.getAll(MotionBlock));
        this.mediafilesObserver = new BehaviorSubject(DS.getAll(Mediafile));
        this.agendaItemObserver = new BehaviorSubject(DS.getAll(Item));

        // Make sure the subjects are updated, when a new Model for the type arrives
        this.DS.changeObservable.subscribe(newModel => {
            if (newModel instanceof User) {
                this.submitterObserver.next(DS.getAll(User));
                this.supporterObserver.next(DS.getAll(User));
            } else if (newModel instanceof Category) {
                this.categoryObserver.next(DS.getAll(Category));
            } else if (newModel instanceof Workflow) {
                this.workflowObserver.next(DS.getAll(Workflow));
            } else if (newModel instanceof MotionBlock) {
                this.blockObserver.next(DS.getAll(MotionBlock));
            } else if (newModel instanceof Mediafile) {
                this.mediafilesObserver.next(DS.getAll(Mediafile));
            } else if (newModel instanceof Item) {
                this.agendaItemObserver.next(DS.getAll(Item));
            }
        });

        // load config variables
        this.configService.get('motions_statutes_enabled').subscribe(enabled => (this.statutesEnabled = enabled));
        this.configService.get('motions_min_supporters').subscribe(supporters => (this.minSupporters = supporters));
        this.configService.get('motions_preamble').subscribe(preamble => (this.preamble = preamble));
        this.configService.get('motions_amendments_enabled').subscribe(enabled => (this.amendmentsEnabled = enabled));
        this.configService.get('motions_line_length').subscribe(lineLength => (this.lineLength = lineLength));
        this.configService.get('motions_default_line_numbering').subscribe(mode => (this.lnMode = mode));
        this.configService.get('motions_recommendation_text_mode').subscribe(mode => (this.crMode = mode));
    }

    /**
     * Init.
     * Sets the surrounding motions to navigate back and forth
     */
    public ngOnInit(): void {
        this.createForm();
        this.getMotionByUrl();

        this.repo.getViewModelListObservable().subscribe(newMotionList => {
            if (newMotionList) {
                this.allMotions = newMotionList;
                this.setSurroundingMotions();
            }
        });

        this.statuteRepo.getViewModelListObservable().subscribe(newViewStatuteParagraphs => {
            this.statuteParagraphs = newViewStatuteParagraphs;
        });

        // Set the default visibility using observers
        this.agendaRepo.getDefaultAgendaVisibility().subscribe(visibility => {
            if (visibility && this.newMotion) {
                this.contentForm.get('agenda_type').setValue(visibility);
            }
        });

        // disable the selector for attachments if there are none
        this.mediafilesObserver.subscribe(files => {
            if (this.createForm) {
                const attachmentsCtrl = this.contentForm.get('attachments_id');
                if (this.mediafilesObserver.value.length === 0) {
                    attachmentsCtrl.disable();
                } else {
                    attachmentsCtrl.enable();
                }
            }
        });
    }

    /**
     * Merges amendments and change recommendations and sorts them by the line numbers.
     * Called each time one of these arrays changes.
     */
    private recalcUnifiedChanges(): void {
        this.allChangingObjects = [];
        if (this.changeRecommendations) {
            this.changeRecommendations.forEach(
                (change: ViewUnifiedChange): void => {
                    this.allChangingObjects.push(change);
                }
            );
        }
        if (this.amendments) {
            this.amendments.forEach(
                (amendment: ViewMotion): void => {
                    this.repo.getAmendmentAmendedParagraphs(amendment, this.lineLength).forEach(
                        (change: ViewUnifiedChange): void => {
                            this.allChangingObjects.push(change);
                        }
                    );
                }
            );
        }
        this.allChangingObjects.sort((a: ViewUnifiedChange, b: ViewUnifiedChange) => {
            if (a.getLineFrom() < b.getLineFrom()) {
                return -1;
            } else if (a.getLineFrom() > b.getLineFrom()) {
                return 1;
            } else {
                return 0;
            }
        });
    }

    /**
     * determine the motion to display using the URL
     */
    public getMotionByUrl(): void {
        if (this.route.snapshot.url[0] && this.route.snapshot.url[0].path === 'new') {
            // creates a new motion
            this.newMotion = true;
            this.editMotion = true;
            this.motion = new ViewCreateMotion();
            this.motionCopy = new ViewCreateMotion();
        } else {
            // load existing motion
            this.route.params.subscribe(params => {
                const motionId: number = parseInt(params.id, 10);
                this.repo.getViewModelObservable(motionId).subscribe(newViewMotion => {
                    if (newViewMotion) {
                        this.motion = newViewMotion;
                        this.personalNoteService.getPersonalNoteObserver(this.motion.motion).subscribe(pn => {
                            this.personalNoteContent = pn;
                        });
                        this.patchForm(this.motion);
                    }
                });
                this.repo.amendmentsTo(motionId).subscribe(
                    (amendments: ViewMotion[]): void => {
                        this.amendments = amendments;
                        this.recalcUnifiedChanges();
                    }
                );
                this.changeRecoRepo.getChangeRecosOfMotionObservable(motionId).subscribe((recos: ViewChangeReco[]) => {
                    this.changeRecommendations = recos;
                    this.recalcUnifiedChanges();
                });
            });
        }
    }

    /**
     * Async load the values of the motion in the Form.
     */
    public patchForm(formMotion: ViewMotion): void {
        const contentPatch: { [key: string]: any } = {};
        Object.keys(this.contentForm.controls).forEach(ctrl => {
            contentPatch[ctrl] = formMotion[ctrl];
        });

        if (formMotion.isParagraphBasedAmendment()) {
            contentPatch.text = formMotion.amendment_paragraphs.find(
                (para: string): boolean => {
                    return para !== null;
                }
            );
        }

        const statuteAmendmentFieldName = 'statute_amendment';
        contentPatch[statuteAmendmentFieldName] = formMotion.isStatuteAmendment();
        this.contentForm.patchValue(contentPatch);
    }

    /**
     * Creates the forms for the Motion and the MotionVersion
     *
     * TODO: Build a custom form validator
     */
    public createForm(): void {
        this.contentForm = this.formBuilder.group({
            identifier: [''],
            title: ['', Validators.required],
            text: ['', Validators.required],
            reason: [''],
            category_id: [''],
            attachments_id: [[]],
            agenda_parent_id: [],
            agenda_type: [''],
            submitters_id: [],
            supporters_id: [[]],
            workflow_id: [],
            origin: [''],
            statute_amendment: [''], // Internal value for the checkbox, not saved to the model
            statute_paragraph_id: ['']
        });
        this.updateWorkflowIdForCreateForm();
    }

    /**
     * clicking Shift and Enter will save automatically
     *
     * @param event has the code
     */
    public onKeyDown(event: KeyboardEvent): void {
        if (event.key === 'Enter' && event.shiftKey) {
            this.saveMotion();
        }
    }

    /**
     * Before updating or creating, the motions needs to be prepared for paragraph based amendments.
     * A motion of type T is created, prepared and deserialized from the given motionValues
     *
     * @param motionValues valus for the new motion
     * @param ctor The motion constructor, so different motion types can be created.
     *
     * @returns the motion to save
     */
    private prepareMotionForSave<T extends Motion>(motionValues: any, ctor: new (...args: any[]) => T): T {
        const motion = new ctor();
        if (this.motion.isParagraphBasedAmendment()) {
            motion.amendment_paragraphs = this.motion.amendment_paragraphs.map(
                (paragraph: string): string => {
                    if (paragraph === null) {
                        return null;
                    } else {
                        return motionValues.text;
                    }
                }
            );
            motionValues.text = '';
        }

        motion.deserialize(motionValues);
        return motion;
    }

    /**
     * Creates a motion. Calls the "patchValues" function in the MotionObject
     */
    public async createMotion(): Promise<void> {
        const newMotionValues = { ...this.contentForm.value };

        if (!newMotionValues.agenda_parent_id) {
            delete newMotionValues.agenda_parent_id;
        }

        const motion = this.prepareMotionForSave(newMotionValues, CreateMotion);

        try {
            const response = await this.repo.create(motion);
            this.router.navigate(['./motions/' + response.id]);
        } catch (e) {
            this.raiseError(e);
        }
    }

    /**
     * Save a motion. Calls the "patchValues" function in the MotionObject
     */
    public async updateMotion(): Promise<void> {
        const newMotionValues = { ...this.contentForm.value };
        const motion = this.prepareMotionForSave(newMotionValues, Motion);
        this.repo.update(motion, this.motionCopy).then(() => (this.editMotion = false), this.raiseError);
    }

    /**
     * In the ui are no distinct buttons for update or create. This is decided here.
     */
    public saveMotion(): void {
        if (this.newMotion) {
            this.createMotion();
        } else {
            this.updateMotion();
        }
    }

    /**
     * get the formated motion text from the repository.
     *
     * @returns formated motion texts
     */
    public getFormattedTextPlain(): string {
        // Prevent this.allChangingObjects to be reordered from within formatMotion
        const changes: ViewUnifiedChange[] = Object.assign([], this.allChangingObjects);
        return this.repo.formatMotion(this.motion.id, this.crMode, changes, this.lineLength, this.highlightedLine);
    }

    /**
     * Called from the template to make a HTML string compatible with [innerHTML]
     * (otherwise line-number-data-attributes would be stripped out)
     *
     * @param {string} text
     * @returns {SafeHtml}
     */
    public sanitizedText(text: string): SafeHtml {
        return this.sanitizer.bypassSecurityTrustHtml(text);
    }

    /**
     * If `this.motion` is an amendment, this returns the list of all changed paragraphs.
     *
     * @returns {DiffLinesInParagraph[]}
     */
    public getAmendedParagraphs(): DiffLinesInParagraph[] {
        return this.repo.getAmendedParagraphs(this.motion, this.lineLength);
    }

    /**
     * If `this.motion` is an amendment, this returns a specified line range from the parent motion
     * (e.g. to show the contect in which this amendment is happening)
     *
     * @param from the line number to start
     * @param to the line number to stop
     * @returns safe html strings
     */
    public getParentMotionRange(from: number, to: number): SafeHtml {
        const str = this.repo.extractMotionLineRange(this.motion.parent_id, { from, to }, true, this.lineLength);
        return this.sanitizer.bypassSecurityTrustHtml(str);
    }

    /**
     * get the diff html from the statute amendment, as SafeHTML for [innerHTML]
     *
     * @returns safe html strings
     */
    public getFormattedStatuteAmendment(): SafeHtml {
        const diffHtml = this.repo.formatStatuteAmendment(this.statuteParagraphs, this.motion, this.lineLength);
        return this.sanitizer.bypassSecurityTrustHtml(diffHtml);
    }

    /**
     * Trigger to delete the motion.
     */
    public async deleteMotionButton(): Promise<void> {
        const content = this.translate.instant('Are you sure you want to delete this motion?');
        if (await this.promptService.open(this.motion.title, content)) {
            await this.repo.delete(this.motion);
            this.router.navigate(['./motions/']);
        }
    }

    /**
     * Sets the motions line numbering mode
     *
     * @param mode Needs to got the enum defined in ViewMotion
     */
    public setLineNumberingMode(mode: LineNumberingMode): void {
        this.lnMode = mode;
    }

    /**
     * Returns true if no line numbers are to be shown.
     *
     * @returns whether there are line numbers at all
     */
    public isLineNumberingNone(): boolean {
        return this.lnMode === LineNumberingMode.None;
    }

    /**
     * Returns true if the line numbers are to be shown within the text with no line breaks.
     *
     * @returns whether the line numberings are inside
     */
    public isLineNumberingInline(): boolean {
        return this.lnMode === LineNumberingMode.Inside;
    }

    /**
     * Returns true if the line numbers are to be shown to the left of the text.
     *
     * @returns whether the line numberings are outside
     */
    public isLineNumberingOutside(): boolean {
        return this.lnMode === LineNumberingMode.Outside;
    }

    /**
     * Sets the motions change reco mode
     * @param mode Needs to fot to the enum defined in ViewMotion
     */
    public setChangeRecoMode(mode: ChangeRecoMode): void {
        this.crMode = mode;
    }

    /**
     * Returns true if the original version (including change recommendation annotation) is to be shown
     */
    public isRecoModeOriginal(): boolean {
        return this.crMode === ChangeRecoMode.Original || this.allChangingObjects.length === 0;
    }

    /**
     * Returns true if the diff version is to be shown
     */
    public isRecoModeDiff(): boolean {
        return this.crMode === ChangeRecoMode.Diff && this.allChangingObjects.length > 0;
    }

    /**
     * In the original version, a line number range has been selected in order to create a new change recommendation
     *
     * @param lineRange
     */
    public createChangeRecommendation(lineRange: LineRange): void {
        const data: MotionChangeRecommendationComponentData = {
            editChangeRecommendation: false,
            newChangeRecommendation: true,
            lineRange: lineRange,
            changeRecommendation: this.repo.createChangeRecommendationTemplate(
                this.motion.id,
                lineRange,
                this.lineLength
            )
        };
        this.dialogService.open(MotionChangeRecommendationComponent, {
            height: '400px',
            width: '600px',
            data: data
        });
    }

    /**
     * In the original version, a change-recommendation-annotation has been clicked
     * -> Go to the diff view and scroll to the change recommendation
     */
    public gotoChangeRecommendation(changeRecommendation: ViewChangeReco): void {
        this.scrollToChange = changeRecommendation;
        this.setChangeRecoMode(ChangeRecoMode.Diff);
    }

    /**
     * Goes to the amendment creation wizard. Executed via click.
     */
    public createAmendment(): void {
        this.router.navigate(['./create-amendment'], { relativeTo: this.route });
    }

    /**
     * Comes from the head bar
     *
     * @param mode
     */
    public setEditMode(mode: boolean): void {
        this.editMotion = mode;
        if (mode) {
            this.motionCopy = this.motion.copy();
            this.patchForm(this.motionCopy);
            if (this.vp.isMobile) {
                this.metaInfoPanel.open();
                this.contentPanel.open();
            }
        }
        if (!mode && this.newMotion) {
            this.router.navigate(['./motions/']);
        }
    }

    /**
     * Sets the default workflow ID during form creation
     */
    public updateWorkflowIdForCreateForm(): void {
        const isStatuteAmendment = !!this.contentForm.get('statute_amendment').value;
        const configKey = isStatuteAmendment ? 'motions_statute_amendments_workflow' : 'motions_workflow';
        // TODO: This should just be a takeWhile(id => !id), but should include the last one where the id is OK.
        // takeWhile will get a inclusive parameter, see https://github.com/ReactiveX/rxjs/pull/4115
        this.configService
            .get<string>(configKey)
            .pipe(
                multicast(
                    () => new ReplaySubject(1),
                    ids =>
                        ids.pipe(
                            takeWhile(id => !id),
                            o => concat(o, ids.pipe(take(1)))
                        )
                ),
                skipWhile(id => !id)
            )
            .subscribe(id => {
                this.contentForm.patchValue({
                    workflow_id: parseInt(id, 10)
                });
            });
    }

    /**
     * If the checkbox is deactivated, the statute_paragraph_id-field needs to be reset, as only that field is saved
     *
     * @param {MatCheckboxChange} $event
     */
    public onStatuteAmendmentChange($event: MatCheckboxChange): void {
        this.contentForm.patchValue({
            statute_paragraph_id: null
        });
        this.updateWorkflowIdForCreateForm();
    }

    /**
     * The paragraph of the statute to amend was changed -> change the input fields below
     *
     * @param {number} newValue
     */
    public onStatuteParagraphChange(newValue: number): void {
        const selectedParagraph = this.statuteParagraphs.find(par => par.id === newValue);
        this.contentForm.patchValue({
            title: this.translate.instant('Statute amendment for') + ` ${selectedParagraph.title}`,
            text: selectedParagraph.text
        });
    }

    /**
     * Navigates the user to the given ViewMotion
     *
     * @param motion target
     */
    public navigateToMotion(motion: ViewMotion): void {
        this.router.navigate(['../' + motion.id], { relativeTo: this.route });
        // update the current motion
        this.motion = motion;
        this.setSurroundingMotions();
    }

    /**
     * Sets the previous and next motion
     */
    public setSurroundingMotions(): void {
        const indexOfCurrent = this.allMotions.findIndex(motion => {
            return motion === this.motion;
        });
        if (indexOfCurrent > -1) {
            if (indexOfCurrent > 0) {
                this.previousMotion = this.allMotions[indexOfCurrent - 1];
            } else {
                this.previousMotion = null;
            }

            if (indexOfCurrent < this.allMotions.length - 1) {
                this.nextMotion = this.allMotions[indexOfCurrent + 1];
            } else {
                this.nextMotion = null;
            }
        }
    }

    /**
     * Supports the motion (as requested user)
     */
    public support(): void {
        this.repo.support(this.motion).then(null, this.raiseError);
    }

    /**
     * Unsupports the motion
     */
    public unsupport(): void {
        this.repo.unsupport(this.motion).then(null, this.raiseError);
    }

    /**
     * Opens the dialog with all supporters.
     * TODO: open dialog here!
     */
    public openSupportersDialog(): void {
        this.showSupporters = !this.showSupporters;
    }

    /**
     * Sets the state
     *
     * @param id Motion state id
     */
    public setState(id: number): void {
        this.repo.setState(this.motion, id);
    }

    /**
     * Sets the recommendation
     *
     * @param id Motion recommendation id
     */
    public setRecommendation(id: number): void {
        this.repo.setRecommendation(this.motion, id);
    }

    /**
     * Sets the category for current motion
     *
     * @param id Motion category id
     */
    public setCategory(id: number): void {
        if (id === this.motion.category_id) {
            this.repo.setCatetory(this.motion, null);
        } else {
            this.repo.setCatetory(this.motion, id);
        }
    }

    /**
     * Add the current motion to a motion block
     *
     * @param id Motion block id
     */
    public setBlock(id: number): void {
        if (id === this.motion.motion_block_id) {
            this.repo.setBlock(this.motion, null);
        } else {
            this.repo.setBlock(this.motion, id);
        }
    }

    /**
     * Observes the repository for changes in the motion recommender
     */
    public setupRecommender(): void {
        const configKey = this.motion.isStatuteAmendment()
            ? 'motions_statute_recommendations_by'
            : 'motions_recommendations_by';
        if (this.recommenderSubscription) {
            this.recommenderSubscription.unsubscribe();
        }
        this.recommenderSubscription = this.configService.get(configKey).subscribe(recommender => {
            this.recommender = recommender;
        });
    }

    /**
     * Create the absolute path to the corresponding list of speakers
     *
     * @returns the link to the corresponding list of speakers as string
     */
    public getSpeakerLink(): string {
        return `/agenda/${this.motion.agenda_item_id}/speakers`;
    }

    /**
     * Click handler for the pdf button
     */
    public onDownloadPdf(): void {
        this.pdfExport.exportSingleMotion(this.motion, this.lnMode, this.crMode);
    }

    /**
     * Click handler for attachments
     *
     * @param attachment the selected file
     */
    public onClickAttacment(attachment: Mediafile): void {
        window.open(attachment.getDownloadUrl());
    }

    /**
     * Determine if the user has the correct requirements to alter the motion
     * TODO: All views should probably have a "isAllowedTo" routine to simplify this process
     *
     * @returns whether or not the OP is allowed to edit the motion
     */
    public opCanEdit(): boolean {
        return this.op.hasPerms('motions.can_manage', 'motions.can_manage_metadata');
    }

    public async createPoll(): Promise<void> {
        await this.repo.createPoll(this.motion);
    }

    /**
     * Check if a recommendation can be followed. Checks for permissions and additionally if a recommentadion is present
     */
    public get canFollowRecommendation(): boolean {
        if (
            this.perms.isAllowed('createPoll', this.motion) &&
            this.motion.recommendation &&
            this.motion.recommendation.recommendation_label
        ) {
            return true;
        }
        return false;
    }

    /**
     * Handler for the 'follow recommendation' button
     */
    public onFollowRecButton(): void {
        this.repo.followRecommendation(this.motion);
    }

    /**
     * Toggles the favorite status
     */
    public async toggleFavorite(): Promise<void> {
        this.personalNoteService.setPersonalNoteStar(this.motion.motion, !this.motion.star);
    }
}
