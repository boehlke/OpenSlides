import { Component } from '@angular/core';
import { MatSnackBar } from '@angular/material';
import { Title } from '@angular/platform-browser';
import { TranslateService } from '@ngx-translate/core';

import { BaseImportListComponent } from 'app/site/base/base-import-list';
import { FileExportService } from 'app/core/services/file-export.service';
import { FormBuilder, FormGroup } from '@angular/forms';
import { NewEntry } from 'app/core/services/base-import.service';
import { UserImportService } from '../../services/user-import.service';
import { ViewUser } from '../../models/view-user';

/**
 * Component for the user import list view.
 */
@Component({
    selector: 'os-user-import-list',
    templateUrl: './user-import-list.component.html'
})
export class UserImportListComponent extends BaseImportListComponent<ViewUser> {
    public textAreaForm: FormGroup;

    /**
     * Constructor for list view bases
     *
     * @param titleService the title serivce
     * @param matSnackBar snackbar for displaying errors
     * @param formBuilder: FormBuilder for the textArea
     * @param translate the translate service
     * @param exporter: csv export service for dummy dat
     * @param importer: The motion csv import service
     */
    public constructor(
        titleService: Title,
        matSnackBar: MatSnackBar,
        formBuilder: FormBuilder,
        public translate: TranslateService,
        private exporter: FileExportService,
        importer: UserImportService
    ) {
        super(importer, titleService, translate, matSnackBar);
        this.textAreaForm = formBuilder.group({ inputtext: [''] });
    }

    /**
     * Triggers an example csv download
     */
    public downloadCsvExample(): void {
        const headerRow = [
            'Title',
            'Given name',
            'Surname',
            'Structure level',
            'Participant number',
            'Groups',
            'Comment',
            'Is active',
            'Is present',
            'Is a committee',
            'Initial password',
            'Email'
        ]
            .map(item => this.translate.instant(item))
            .join(',');
        const rows = [
            headerRow,
            'Dr.,Max,Mustermann,"Berlin",1234567890,"Delegates, Staff",xyz,1,1,,initialPassword,',
            ',John,Doe,Washington,75/99/8-2,Committees,"This is a comment, without doubt",1,1,,,john.doe@email.com',
            ',Fred,Bloggs,London,,,,,,,,',
            ',,Executive Board,,,,,,,1,,'
        ];
        this.exporter.saveFile(rows.join('\n'), this.translate.instant('User example') + '.csv');
    }

    /**
     * Shorthand for getVerboseError on name fields checking for duplicates and invalid fields
     *
     * @param row
     * @returns an error string similar to getVerboseError
     */
    public nameErrors(row: NewEntry<ViewUser>): string {
        for (const name of ['NoName', 'Duplicates', 'DuplicateImport']) {
            if (this.importer.hasError(row, name)) {
                return this.importer.verbose(name);
            }
        }
        return '';
    }

    /**
     * Sends the data in the text field input area to the importer
     */
    public parseTextArea(): void {
        (this.importer as UserImportService).parseTextArea(this.textAreaForm.get('inputtext').value);
    }

    /**
     * Triggers a change in the tab group: Clearing the preview selection
     */
    public onTabChange(): void {
        this.importer.clearPreview();
    }
}
