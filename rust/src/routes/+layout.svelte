<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { locale, t } from '$lib/i18n';
	import { project } from '$lib/stores';

	let { children } = $props();

	onMount(async () => {
		try {
			$locale = (await api.getSettings()).locale ?? 'en';
		} catch {
			// English stays: a settings read failing must not blank the interface.
		}
	});
</script>

<div class="app-shell">
	<header>
		<a class="brand" href="/">Ren'Py Translation Studio</a>
		{#if $project}
			<span class="project-summary">
				{$project.gameName} · {$project.sourceLanguage} → {$project.targetLanguage || '?'}
			</span>
		{/if}
		<nav>
			<a href="/">{$t('project_setup.step_setup')}</a>
			<a href="/review" class:disabled={!$project}>{$t('project_setup.step_review')}</a>
			<a href="/characters" class:disabled={!$project}>{$t('characters.title')}</a>
			<a href="/universe" class:disabled={!$project}>{$t('universe.title')}</a>
			<a href="/export" class:disabled={!$project}>{$t('project_setup.step_export')}</a>
			<a href="/provider-config">{$t('provider_config.title')}</a>
		</nav>
	</header>
	<main>
		{@render children()}
	</main>
</div>

<style>
	:global(html, body) {
		margin: 0;
		font-family:
			system-ui,
			-apple-system,
			'Segoe UI',
			sans-serif;
		color: #1a1a1a;
		background: #fafafa;
	}

	:global(*) {
		box-sizing: border-box;
	}

	:global(button) {
		font: inherit;
		cursor: pointer;
	}

	:global(button:disabled) {
		cursor: not-allowed;
		opacity: 0.5;
	}

	:global(input, textarea, select) {
		font: inherit;
	}

	:global(table) {
		border-collapse: collapse;
		width: 100%;
	}

	:global(h1) {
		font-size: 1.4rem;
	}

	:global(h2) {
		font-size: 1.1rem;
	}

	.app-shell {
		display: flex;
		flex-direction: column;
		height: 100vh;
	}

	header {
		display: flex;
		align-items: center;
		gap: 1.5rem;
		padding: 0.6rem 1rem;
		background: #22252b;
		color: #eee;
		flex-shrink: 0;
	}

	.brand {
		font-weight: 600;
		color: #fff;
		text-decoration: none;
	}

	.project-summary {
		color: #bbb;
		font-size: 0.85rem;
		flex: 1;
	}

	nav {
		display: flex;
		gap: 0.9rem;
	}

	nav a {
		color: #ccc;
		text-decoration: none;
		font-size: 0.9rem;
	}

	nav a:hover {
		color: #fff;
	}

	nav a.disabled {
		color: #555;
		pointer-events: none;
	}

	main {
		flex: 1;
		overflow: auto;
		padding: 1rem 1.5rem;
	}
</style>
