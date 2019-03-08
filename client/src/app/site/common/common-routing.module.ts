import { NgModule } from '@angular/core';
import { Routes, RouterModule } from '@angular/router';

import { PrivacyPolicyComponent } from './components/privacy-policy/privacy-policy.component';
import { StartComponent } from './components/start/start.component';
import { LegalNoticeComponent } from './components/legal-notice/legal-notice.component';
import { SearchComponent } from './components/search/search.component';

const routes: Routes = [
    {
        path: '',
        component: StartComponent,
        pathMatch: 'full'
    },
    {
        path: 'legalnotice',
        component: LegalNoticeComponent
    },
    {
        path: 'privacypolicy',
        component: PrivacyPolicyComponent
    },
    {
        path: 'search',
        component: SearchComponent
    }
];

@NgModule({
    imports: [RouterModule.forChild(routes)],
    exports: [RouterModule]
})
export class CommonRoutingModule {}
