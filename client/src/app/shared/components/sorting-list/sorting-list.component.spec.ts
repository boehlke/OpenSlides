import { async, ComponentFixture, TestBed } from '@angular/core/testing';
import { E2EImportsModule } from '../../../../e2e-imports.module';
import { SortingListComponent } from './sorting-list.component';
import { Component, ViewChild } from '@angular/core';
import { Selectable } from '../selectable';
import { EmptySelectable } from '../empty-selectable';

describe('SortingListComponent', () => {
    @Component({
        selector: 'os-host-component',
        template: '<os-sorting-list><os-sorting-list>'
    })
    class TestHostComponent {
        @ViewChild(SortingListComponent)
        public sortingListCompononent: SortingListComponent;
    }

    let hostComponent: TestHostComponent;
    let hostFixture: ComponentFixture<TestHostComponent>;

    beforeEach(async(() => {
        TestBed.configureTestingModule({
            imports: [E2EImportsModule],
            declarations: [TestHostComponent]
        }).compileComponents();
    }));

    beforeEach(() => {
        hostFixture = TestBed.createComponent(TestHostComponent);
        hostComponent = hostFixture.componentInstance;
    });

    it('should create', () => {
        const inputList: Array<Selectable> = [];
        for (let index = 0; index < 20; index++) {
            inputList.push(new EmptySelectable());
        }
        hostComponent.sortingListCompononent.input = inputList;

        hostFixture.detectChanges();
        expect(hostComponent.sortingListCompononent).toBeTruthy();
    });
});
