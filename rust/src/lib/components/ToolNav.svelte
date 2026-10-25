<script lang="ts">
	// Characters / Universe / Providers links and the settings button.
	// Disabled like the steps: no project, or a job running.
	import { page } from '$app/state';
	import { t } from '$lib/i18n';
	import { blockMessageKey, blockReason, normalizePath, ROUTES } from '$lib/navigation';
	import { jobRunning, project, settingsOpen } from '$lib/stores';

	const tools = [
		{ href: ROUTES.characters, labelKey: 'nav.characters' },
		{ href: ROUTES.universe, labelKey: 'nav.universe' },
		{ href: ROUTES.providers, labelKey: 'nav.providers' }
	];

	const path = $derived(normalizePath(page.url.pathname));

	const items = $derived(
		tools.map((tool) => ({
			...tool,
			current: path === tool.href,
			reason: blockReason(tool.href, { hasProject: $project !== null, jobRunning: $jobRunning })
		}))
	);
</script>

<nav aria-label={$t('nav.tools')}>
	<ul>
		{#each items as tool (tool.href)}
			<li>
				{#if tool.reason}
					<span class="btn ghost" aria-disabled="true" title={$t(blockMessageKey(tool.reason))}>
						{$t(tool.labelKey)}<span class="sr"> ({$t(blockMessageKey(tool.reason))})</span>
					</span>
				{:else}
					<a
						class="btn ghost"
						href={tool.href}
						aria-current={tool.current ? 'page' : undefined}
					>
						{$t(tool.labelKey)}
					</a>
				{/if}
			</li>
		{/each}
		<li>
			<!-- The settings dialog is built separately: it listens to `settingsOpen`. -->
			<button
				type="button"
				class="btn ghost icon"
				aria-label={$t('settings.title')}
				title={$t('settings.title')}
				onclick={() => settingsOpen.set(true)}
			>
				<svg
					class="ico"
					viewBox="0 0 16 16"
					fill="none"
					stroke="currentColor"
					stroke-width="1.4"
					stroke-linecap="round"
					aria-hidden="true"
				>
					<path d="M2.5 4.5h7M12.5 4.5h1M2.5 11.5h1M6.5 11.5h7" />
					<circle cx="11" cy="4.5" r="1.5" />
					<circle cx="5" cy="11.5" r="1.5" />
				</svg>
			</button>
		</li>
	</ul>
</nav>

<style>
	ul {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 2px;
		list-style: none;
		margin: 0;
		padding: 0;
	}

	a[aria-current='page'] {
		background: var(--accWeak);
		color: var(--acc7);
		font-weight: 600;
	}
</style>
