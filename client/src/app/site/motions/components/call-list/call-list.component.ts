import { Component, EventEmitter } from '@angular/core';
import { Title } from '@angular/platform-browser';
import { MatSnackBar } from '@angular/material';

import { TranslateService } from '@ngx-translate/core';
import { Observable } from 'rxjs';

import { BaseViewComponent } from '../../../base/base-view';
import { MotionRepositoryService } from '../../services/motion-repository.service';
import { ViewMotion } from '../../models/view-motion';
import { OSTreeSortEvent } from 'app/shared/components/sorting-tree/sorting-tree.component';
import { MotionCsvExportService } from '../../services/motion-csv-export.service';

/**
 * Sort view for the call list.
 */
@Component({
    selector: 'os-call-list',
    templateUrl: './call-list.component.html'
})
export class CallListComponent extends BaseViewComponent {
    /**
     * All motions sorted first by weight, then by id.
     */
    public motionsObservable: Observable<ViewMotion[]>;

    /**
     * Holds all motions for the export.
     */
    private motions: ViewMotion[] = [];

    /**
     * Emits true for expand and false for collaps. Informs the sorter component about this actions.
     */
    public readonly expandCollapse: EventEmitter<boolean> = new EventEmitter<boolean>();

    /**
     * Updates the motions member, and sorts it.
     * @param title
     * @param translate
     * @param matSnackBar
     * @param motionRepo
     */
    public constructor(
        title: Title,
        translate: TranslateService,
        matSnackBar: MatSnackBar,
        private motionRepo: MotionRepositoryService,
        private motionCsvExport: MotionCsvExportService
    ) {
        super(title, translate, matSnackBar);

        this.motionsObservable = this.motionRepo.getViewModelListObservable();
        this.motionsObservable.subscribe(motions => {
            // Sort motions and make a copy, so it will stay sorted.
            this.motions = motions.map(x => x).sort((a, b) => a.callListWeight - b.callListWeight);
        });
    }

    /**
     * Handler for the sort event. The data to change is given to
     * the repo, sending it to the server.
     *
     * @param data The event data. The representation fits the servers requirements, so it can directly
     * be send to the server via the repository.
     */
    public sort(data: OSTreeSortEvent<ViewMotion>): void {
        this.motionRepo.sortMotions(data).then(null, this.raiseError);
    }

    /**
     * Fires the expandCollapse event emitter.
     *
     * @param expand True, if the tree should be expanded. Otherwise collapsed
     */
    public expandCollapseAll(expand: boolean): void {
        this.expandCollapse.emit(expand);
    }

    /**
     * Export the full call list as csv.
     */
    public csvExportCallList(): void {
        this.motionCsvExport.exportCallList(this.motions);
    }
}
