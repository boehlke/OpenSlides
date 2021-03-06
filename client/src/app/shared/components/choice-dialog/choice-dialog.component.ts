import { Component, Inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material';
import { Displayable } from 'app/shared/models/base/displayable';
import { Identifiable } from 'app/shared/models/base/identifiable';

/**
 * An option needs to be identifiable and should have a strnig to display. Either uses Displayble or
 * a label property.
 */
type ChoiceDialogOption = (Identifiable & Displayable) | (Identifiable & { label: string });

/**
 * All choices in the array should have the same type.
 */
export type ChoiceDialogOptions = (Identifiable & Displayable)[] | (Identifiable & { label: string })[];

/**
 * All data needed for this dialog
 */
interface ChoiceDialogData {
    /**
     * A title to display
     */
    title: string;

    /**
     * The choices to display
     */
    choices: ChoiceDialogOptions;

    /**
     * Select if this should be a multiselect choice
     */
    multiSelect: boolean;

    /**
     * Additional action buttons which will add their value to the
     * {@link closeDialog} feedback if chosen
     */
    actionButtons?: string[];

    /**
     * An optional string for 'explicitly select none of the options'. Only
     * displayed in the single-select variation
     */
    clearChoice?: string;
}

/**
 * undefined is returned, if the dialog is closed. If a choice is submitted,
 * it will be an array of numbers and optionally an action string for multichoice
 * dialogs
 */
export type ChoiceAnswer = undefined | { action?: string; items: number | number[] };

/**
 * A dialog with choice fields.
 *
 */
@Component({
    selector: 'os-choice-dialog',
    templateUrl: './choice-dialog.component.html',
    styleUrls: ['./choice-dialog.component.scss']
})
export class ChoiceDialogComponent {
    /**
     * One number selected, if this is a single select choice
     */
    public selectedChoice: number;

    /**
     * All selected ids, if this is a multiselect choice
     */
    public selectedMultiChoices: number[] = [];

    public constructor(
        public dialogRef: MatDialogRef<ChoiceDialogComponent>,
        @Inject(MAT_DIALOG_DATA) public data: ChoiceDialogData
    ) {}

    /**
     * Get the title from a choice. Maybe saved in a label property or using getTitle().
     *
     * @param choice The choice
     * @return the title
     */
    public getChoiceTitle(choice: ChoiceDialogOption): string {
        if ('label' in choice) {
            return choice.label;
        } else {
            return choice.getTitle();
        }
    }

    /**
     * Closes the dialog with the selected choices
     */
    public closeDialog(ok: boolean, action?: string): void {
        if (!this.data.multiSelect && this.selectedChoice === null) {
            action = this.data.clearChoice;
        }
        if (ok) {
            this.dialogRef.close({
                action: action ? action : null,
                items: this.data.multiSelect ? this.selectedMultiChoices : this.selectedChoice
            });
        } else {
            this.dialogRef.close();
        }
    }

    /**
     * For multiSelect: Determines whether a choice has been activated
     * @param choice
     */
    public isChosen(choice: Identifiable): boolean {
        return this.selectedMultiChoices.indexOf(choice.id) >= 0;
    }

    /**
     * For multiSelect: Activates/deactivates a multi-Choice option
     * @param choice
     */
    public toggleChoice(choice: Identifiable): void {
        const idx = this.selectedMultiChoices.indexOf(choice.id);
        if (idx < 0) {
            this.selectedMultiChoices.push(choice.id);
        } else {
            this.selectedMultiChoices.splice(idx, 1);
        }
    }
}
