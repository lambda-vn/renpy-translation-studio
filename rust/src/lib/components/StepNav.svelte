<script lang="ts">
	// Setup > Review > Export as an ordered list; the current step carries
	// aria-current="step". Steps are disabled (with the reason spelled out for
	// screen readers) when no project is open or a translation job is running.
	// Leaving review for setup asks for confirmation first.
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { confirmDialog } from '$lib/confirm';
	import { t } from '$lib/i18n';
	import { blockMessageKey, blockReason, normalizePath, ROUTES } from '$lib/navigation';
	import { jobRunning, project } from '$lib/stores';

	const steps = [
		{ id: 'setup', href: ROUTES.setup, labelKey: 'project_setup.step_setup' },
		{ id: 'review', href: ROUTES.review, labelKey: 'project_setup.step_review' },
		{ id: 'export', href: ROUTES.export, labelKey: 'project_setup.step_export' }
	];

	const path = $derived(normalizePath(page.url.pathname));

	// Characters, universe and providers are side trips from review: setup
	// still counts as done there, but no step is "the current one".
	const progress = $derived(
		path === ROUTES.setup ? 0 : path === ROUTES.export ? 2 : 1
	);

	const items = $derived(
		steps.map((step, index) => {
			const reason = blockReason(step.href, {
				hasProject: $project !== null,
				jobRunning: $jobRunning
			});
			return {
				...step,
				number: index + 1,
				current: path === step.href,
				done: index < progress,
				reason
			};
		})
	);

	async function followStep(event: MouseEvent, href: string) {
		if (href !== ROUTES.setup || path !== ROUTES.review) return;
		event.preventDefault();
		const confirmed = await confirmDialog({
			title: $t('review.back_confirm_title'),
			message: $t('review.back_confirm_message'),
			confirmLabel: $t('review.back_confirm_action')
		});
		if (confirmed) await goto(ROUTES.setup);
	}
</script>

<nav aria-label={$t('nav.steps')}>
	<ol class="steps">
		{#each items as step, index (step.id)}
			{#if index > 0}
				<li aria-hidden="true" class="chevron">
					<svg
						class="ico"
						viewBox="0 0 16 16"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
						stroke-linecap="round"><path d="M6 3.5L10.5 8 6 12.5" /></svg
					>
				</li>
			{/if}
			<li>
				{#if step.current}
					<span class="step" aria-current="step">
						<span class="num" aria-hidden="true">{step.number}</span>{$t(step.labelKey)}
					</span>
				{:else if step.reason}
					<span class="step" aria-disabled="true">
						<svg
							class="ico"
							viewBox="0 0 16 16"
							fill="none"
							stroke="currentColor"
							stroke-width="1.5"
							stroke-linecap="round"
							aria-hidden="true"
						>
							<rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
							<path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" />
						</svg>
						{$t(step.labelKey)}<span class="sr"> ({$t(blockMessageKey(step.reason))})</span>
					</span>
				{:else}
					<a
						class="step"
						href={step.href}
						onclick={(event) => followStep(event, step.href)}
					>
						{#if step.done}
							<svg
								class="ico"
								viewBox="0 0 16 16"
								fill="none"
								stroke="currentColor"
								stroke-width="1.6"
								stroke-linecap="round"
								stroke-linejoin="round"
								aria-hidden="true"><path d="M3 8.5l3.2 3.2L13 4.8" /></svg
							>
						{:else}
							<span class="num" aria-hidden="true">{step.number}</span>
						{/if}
						{$t(step.labelKey)}{#if step.done}<span class="sr"> ({$t('project_setup.step_done')})</span
							>{/if}
					</a>
				{/if}
			</li>
		{/each}
	</ol>
</nav>

<style>
	.steps {
		display: flex;
		align-items: center;
		gap: 2px;
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.chevron {
		display: flex;
		color: var(--line2);
	}

	.step {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		height: 30px;
		padding: 0 12px;
		border-radius: 999px;
		font-size: 13px;
		color: var(--ink2);
		text-decoration: none;
		white-space: nowrap;
	}

	a.step:hover {
		background: var(--sunken);
	}

	.step[aria-current='step'] {
		background: var(--accWeak);
		color: var(--acc7);
		font-weight: 600;
	}

	.step[aria-disabled='true'] {
		color: var(--ink3);
	}

	.num {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 18px;
		height: 18px;
		border: 1px solid currentColor;
		border-radius: 9px;
		font-family: var(--font-mono);
		font-size: 10.5px;
	}
</style>
