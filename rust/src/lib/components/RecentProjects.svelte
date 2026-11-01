<script lang="ts">
	import type { ProjectEntry } from '$lib/api';
	import { t } from '$lib/i18n';
	import { languageName } from '$lib/languages';

	interface Props {
		entries: ProjectEntry[];
		loaded: boolean;
		error: string;
		opening: string;
		onopen: (entry: ProjectEntry) => void;
		ondelete: (entry: ProjectEntry) => void;
	}

	let { entries, loaded, error, opening, onopen, ondelete }: Props = $props();

	function percent(entry: ProjectEntry): number {
		const resume = entry.resume;
		if (!resume || resume.total === 0) return 0;
		return Math.floor((resume.validated * 100) / resume.total);
	}
</script>

<section class="recent" aria-labelledby="h-recent">
	<h1 id="h-recent">{$t('project_setup.list_title')}</h1>

	{#if error}
		<p class="notice err" role="alert">{error}</p>
	{/if}

	{#if loaded && entries.length === 0}
		<p class="empty">{$t('project_setup.list_empty')}</p>
	{:else}
		<ul class="projects">
			{#each entries as entry (entry.path)}
				{@const resume = entry.resume}
				{@const pct = percent(entry)}
				<li class="proj">
					<button
						type="button"
						class="open"
						disabled={!resume || Boolean(opening)}
						title={entry.path}
						onclick={() => onopen(entry)}
					>
						<span class="info">
							<span class="name">{entry.name}</span>
							<span class="meta">
								{#if resume}
									{languageName(resume.sourceLanguage, $t)} → {languageName(
										resume.targetLanguage,
										$t
									)} ·
								{/if}
								<span class="mono">{entry.path}</span>
							</span>
						</span>
						{#if resume}
							<span
								class="prog"
								title={$t('project_setup.recent_lines', {
									total: resume.total,
									validated: resume.validated
								})}
							>
								<span class="mono pct"
									>{pct} %<span class="sr"> {$t('project_setup.validated_sr')}</span></span
								>
								<progress class="ok" value={pct} max="100" aria-hidden="true"></progress>
							</span>
						{:else}
							<span class="prog"
								><span class="mono pct">{$t('extraction.not_extracted')}</span></span
							>
						{/if}
					</button>
					<button
						type="button"
						class="btn ghost icon"
						aria-label={$t('project_setup.delete_label', { name: entry.name })}
						title={$t('project_setup.delete_tooltip')}
						onclick={() => ondelete(entry)}
					>
						<svg
							class="ico"
							viewBox="0 0 16 16"
							fill="none"
							stroke="currentColor"
							stroke-width="1.5"
							stroke-linecap="round"
							aria-hidden="true"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" /></svg
						>
					</button>
				</li>
			{/each}
		</ul>
		{#if entries.length > 0}
			<p class="foot-note">{$t('project_setup.delete_note')}</p>
		{/if}
	{/if}
</section>

<style>
	.recent {
		flex: 999 1 480px;
		min-width: 0;
	}
	.recent h1 {
		margin: 0 0 8px;
		font-size: 22px;
	}
	.empty {
		margin: 0;
		padding: 24px 0;
		border-top: 1px solid var(--line);
		color: var(--ink2);
	}

	.projects {
		list-style: none;
		margin: 0;
		padding: 0;
		border-top: 1px solid var(--line);
	}
	.proj {
		display: flex;
		align-items: center;
		gap: 8px;
		border-bottom: 1px solid var(--line);
	}
	.open {
		flex: 1;
		min-width: 0;
		display: grid;
		grid-template-columns: minmax(0, 1fr) 140px;
		gap: 16px;
		align-items: center;
		padding: 16px 12px;
		margin-left: -12px;
		border: 0;
		border-radius: 10px;
		background: transparent;
		color: var(--ink);
		text-align: left;
	}
	.open:hover:not(:disabled) {
		background: var(--hover);
	}
	.open:hover:not(:disabled) .name {
		color: var(--acc7);
	}
	.open:disabled {
		cursor: default;
		color: var(--ink2);
	}
	.info {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.name {
		font-size: 15px;
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.meta {
		font-size: 13px;
		color: var(--ink3);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.meta .mono {
		font-size: 12px;
	}
	.prog {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.pct {
		font-size: 12.5px;
		color: var(--ink2);
		text-align: right;
	}
	.prog progress {
		height: 4px;
	}
	.foot-note {
		margin: 14px 0 0;
		font-size: 12.5px;
		color: var(--ink3);
	}
</style>
