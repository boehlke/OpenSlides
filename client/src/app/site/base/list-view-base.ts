import { MatTableDataSource, MatTable, MatSort, MatPaginator, MatSnackBar } from '@angular/material';
import { Title } from '@angular/platform-browser';
import { TranslateService } from '@ngx-translate/core';
import { ViewChild } from '@angular/core';

import { BaseViewComponent } from './base-view';
import { BaseViewModel } from './base-view-model';

export abstract class ListViewBaseComponent<V extends BaseViewModel> extends BaseViewComponent {
    /**
     * The data source for a table. Requires to be initialized with a BaseViewModel
     */
    public dataSource: MatTableDataSource<V>;

    /**
     * Toggle for enabling the multiSelect mode. Defaults to false (inactive)
     */
    protected canMultiSelect = false;

    /**
     * Current state of the multi select mode. TODO Could be merged with edit mode?
     */
    private _multiSelectMode = false;

    /**
     * An array of currently selected items, upon which multi select actions can be performed
     * see {@link selectItem}.
     */
    public selectedRows: V[];

    /**
     * The table itself
     */
    @ViewChild(MatTable)
    protected table: MatTable<V>;

    /**
     * Table paginator
     */
    @ViewChild(MatPaginator)
    protected paginator: MatPaginator;

    /**
     * Sorter for a table
     */
    @ViewChild(MatSort)
    protected sort: MatSort;

    /**
     * Constructor for list view bases
     * @param titleService the title serivce
     * @param translate the translate service
     * @param matSnackBar
     */
    public constructor(titleService: Title, translate: TranslateService, matSnackBar: MatSnackBar) {
        super(titleService, translate, matSnackBar);
        this.selectedRows = [];
    }

    /**
     * Children need to call this in their init-function.
     * Calling these three functions in the constructor of this class
     * would be too early, resulting in non-paginated tables
     */
    public initTable(): void {
        this.dataSource = new MatTableDataSource();
        this.dataSource.paginator = this.paginator;
    }

    public onSortButton(itemProperty: string): void {
        let newOrder: 'asc' | 'desc' = 'asc';
        if (itemProperty === this.sort.active) {
            newOrder = this.sort.direction === 'asc' ? 'desc' : 'asc';
        }
        const newSort = {
            disableClear: true,
            id: itemProperty,
            start: newOrder
        };
        this.sort.sort(newSort);
    }

    public onFilterData(filteredDataSource: MatTableDataSource<V>): void {
        this.dataSource = filteredDataSource;
        this.dataSource.paginator = this.paginator;
    }

    public searchFilter(event: string): void {
        this.dataSource.filter = event;
    }

    /**
     * Default click action on selecting an item. In multiselect modus,
     * this just adds/removes from a selection, else it performs a {@link singleSelectAction}
     * @param row The clicked row's {@link ViewModel}
     * @param event The Mouse event
     */
    public selectItem(row: V, event: MouseEvent): void {
        event.stopPropagation();
        if (!this._multiSelectMode) {
            this.singleSelectAction(row);
        } else {
            const idx = this.selectedRows.indexOf(row);
            if (idx < 0) {
                this.selectedRows.push(row);
            } else {
                this.selectedRows.splice(idx, 1);
            }
        }
    }

    /**
     * Method to perform an action on click on a row, if not in MultiSelect Modus.
     * Should be overridden by implementations. Currently there is no default action.
     * @param row a ViewModel
     */
    public singleSelectAction(row: V): void {}

    /**
     * enables/disables the multiSelect Mode
     */
    public toggleMultiSelect(): void {
        if (!this.canMultiSelect || this.isMultiSelect) {
            this._multiSelectMode = false;
            this.clearSelection();
        } else {
            this._multiSelectMode = true;
        }
    }

    /**
     * Select all files in the current data source
     */
    public selectAll(): void {
        this.selectedRows = this.dataSource.data;
    }

    public deselectAll(): void {
        this.selectedRows = [];
    }

    /**
     * Returns the current state of the multiSelect modus
     */
    public get isMultiSelect(): boolean {
        return this._multiSelectMode;
    }

    /**
     * checks if a row is currently selected in the multiSelect modus.
     * @param item The row's entry
     */
    public isSelected(item: V): boolean {
        if (!this._multiSelectMode) {
            return false;
        }
        return this.selectedRows.indexOf(item) >= 0;
    }

    /**
     * Handler to quickly unselect all items.
     */
    public clearSelection(): void {
        this.selectedRows = [];
    }

    /**
     * Checks the array of selected items against the datastore data. This is
     * meant to reselect items by their id even if some of their data changed,
     * and to remove selected data that don't exist anymore.
     * To be called after an update of data. Checks if updated selected items
     * are still present in the dataSource, and (re-)selects them. This should
     * be called as the observed datasource updates.
     */
    protected checkSelection(): void {
        const newSelection = [];
        this.selectedRows.forEach(selectedrow => {
            const newrow = this.dataSource.data.find(item => item.id === selectedrow.id);
            if (newrow) {
                newSelection.push(newrow);
            }
        });
        this.selectedRows = newSelection;
    }
}
