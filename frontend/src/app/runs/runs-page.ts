import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed } from '@angular/core';
import { MatTableModule } from '@angular/material/table';
import { RouterLink } from '@angular/router';

import { listRunsResource } from '../api/@angular/common.gen';
import { errorMessage } from '../shared/api-error';
import { RunStatusPipe } from '../shared/format';
import { PageHeader } from '../shared/ui/page-header';

/** Die letzten Laeufe des Batches, neueste zuerst. */
@Component({
  selector: 'app-runs-page',
  imports: [DatePipe, MatTableModule, PageHeader, RouterLink, RunStatusPipe],
  templateUrl: './runs-page.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RunsPage {
  private readonly resource = listRunsResource(() => ({ query: { limit: 50 } }));

  protected readonly runs = computed(() =>
    this.resource.hasValue() ? this.resource.value() : undefined,
  );
  protected readonly error = computed(() => {
    const error = this.resource.error();
    return error ? errorMessage(error, 'Keine Läufe gefunden.') : undefined;
  });

  protected readonly columns = ['id', 'started_at', 'kind', 'status', 'scored', 'exit_code'];
}
