<script lang="ts" module>
	export interface JobLogEntry {
		time: string;
		message: string;
		error?: boolean;
	}
</script>

<script lang="ts">
	// Non-modal banner for the translation job: the review stays usable.
	import { t } from '$lib/i18n';

	interface Props {
		running: boolean;
		cancelling: boolean;
		/** "DeepL · whole project" */
		summary: string;
		total: number;
		done: number;
		failed: number;
		error: string | null;
		/** What the provider is doing meanwhile; `warn` for a slowdown. */
		notice: { text: string; warn: boolean } | null;
		log: JobLogEntry[];
		oncancel: () => void;
		ondismiss: () => void;
	}

	let {
		running,
		cancelling,
		summary,
		total,
		done,
		failed,
		error,
		notice,
		log,
		oncancel,
		ondismiss
	}: Props = $props();

	let expanded = $state(false);
</script>

<section aria-labelledby="job-title">
	<div class="line">
		{#if running}
			<svg
				class="spin"
				viewBox="0 0 16 16"
				fill="none"
				stroke="currentColor"
				stroke-width="1.8"
				stroke-linecap="round"
				aria-hidden="true"
				><circle cx="8" cy="8" r="6" stroke-opacity=".25" /><path d="M8 2a6 6 0 0 1 6 6" /></svg
			>
		{/if}
		<h2 id="job-title">
			{running ? $t('review.job_running_title') : $t('review.job_finished_title')}
		</h2>
		<span class="summary">{summary}</span>
		<div class="bar">
			<progress value={done} max={Math.max(1, total)} aria-labelledby="job-title"></progress>
			<span class="mono count">{done} / {total}</span>
		</div>
		{#if failed > 0}
			<span class="failed"><span class="mono">{failed}</span> {$t('review.job_failures')}</span>
		{/if}
		<button
			type="button"
			class="btn ghost"
			aria-expanded={expanded}
			aria-controls="job-log"
			onclick={() => (expanded = !expanded)}
		>
			{$t('review.job_log')}
		</button>
		{#if running}
			<button type="button" class="btn" disabled={cancelling} onclick={oncancel}>
				{cancelling ? $t('translation.cancelling') : $t('translation.cancel')}
			</button>
		{:else}
			<button type="button" class="btn" onclick={ondismiss}>{$t('common.close')}</button>
		{/if}
	</div>
	{#if notice}
		<p class="notice" class:warn={notice.warn} role="status">{notice.text}</p>
	{/if}
	{#if error}
		<p class="error" role="alert">{error}</p>
	{/if}
	{#if expanded}
		<ol id="job-log" class="mono" aria-label={$t('review.job_log_label')}>
			{#each log as entry, index (index)}
				<li class:err={entry.error}><time>{entry.time}</time> · {entry.message}</li>
			{:else}
				<li>{$t('review.job_log_empty')}</li>
			{/each}
		</ol>
	{/if}
</section>

<style>
	section {
		margin: 0 28px 6px;
		padding: 12px 16px;
		border-radius: 12px;
		background: var(--accWeak);
		flex: none;
	}

	.line {
		display: flex;
		align-items: center;
		gap: 10px 18px;
		flex-wrap: wrap;
	}

	h2 {
		margin: 0;
		font-size: 13.5px;
		font-weight: 600;
	}

	.spin {
		width: 18px;
		height: 18px;
		color: var(--acc);
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.summary {
		font-size: 13px;
		color: var(--ink2);
	}

	.bar {
		flex: 1 1 180px;
		min-width: 160px;
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.bar progress {
		flex: 1;
		background: var(--panel);
	}

	.bar progress::-webkit-progress-bar {
		background: var(--panel);
	}

	.count {
		font-size: 12.5px;
		color: var(--ink2);
		white-space: nowrap;
	}

	.failed,
	.error {
		font-size: 13px;
		color: var(--err);
	}

	.error {
		margin: 8px 0 0;
	}

	.notice {
		margin: 8px 0 0;
		font-size: 13px;
		color: var(--ink2);
	}
	.notice.warn {
		color: var(--warn);
	}

	ol {
		list-style: none;
		margin: 10px 0 0;
		padding: 8px 12px;
		background: var(--panel);
		border-radius: 8px;
		font-size: 12px;
		line-height: 1.8;
		color: var(--ink2);
		max-height: 180px;
		overflow: auto;
	}

	li.err {
		color: var(--err);
	}
</style>
