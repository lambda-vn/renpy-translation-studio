<script lang="ts">
	import '$lib/styles/app.css';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import ConfirmHost from '$lib/components/ConfirmHost.svelte';
	import HelpDialog from '$lib/components/HelpDialog.svelte';
	import Onboarding from '$lib/components/Onboarding.svelte';
	import SettingsDialog from '$lib/components/SettingsDialog.svelte';
	import ToastHost from '$lib/components/ToastHost.svelte';
	import { locale, t } from '$lib/i18n';
	import { matches } from '$lib/shortcuts';
	import { skipLinks } from '$lib/stores';
	import { setTheme } from '$lib/theme';

	let { children } = $props();

	let helpOpen = $state(false);
	// Read once at startup: the onboarding replaces the shell until it is done.
	let ready = $state(false);
	let firstLaunch = $state(false);

	onMount(async () => {
		try {
			const settings = await api.getSettings();
			$locale = settings.locale ?? 'en';
			setTheme(settings.theme);
			firstLaunch = await api.isFirstLaunch();
		} catch {
			// English and the system theme stay: a settings read failing must
			// not blank the interface.
		}
		ready = true;
	});

	$effect(() => {
		document.documentElement.lang = $locale;
	});

	// F1 works everywhere, fields included. Esc is not handled here: an open
	// <dialog> or menu closes itself, and a screen's own Esc (clearing the
	// search) must check `modalDepth` first.
	function onkeydown(event: KeyboardEvent) {
		if (matches('help', event)) {
			event.preventDefault();
			helpOpen = true;
		}
	}
</script>

<svelte:window {onkeydown} />

{#if !ready}
	<div class="loading"></div>
{:else if firstLaunch}
	<Onboarding ondone={() => (firstLaunch = false)} />
{:else}
	<div class="app-shell">
		<a class="skip" href="#contenu">{$t('nav.skip_to_content')}</a>
		{#each $skipLinks as link (link.href)}
			<a class="skip" href={link.href}>{link.label}</a>
		{/each}
		<AppHeader />
		<main id="contenu" tabindex="-1">
			{@render children()}
		</main>
	</div>

	<HelpDialog bind:open={helpOpen} />
	<SettingsDialog />
{/if}
<ConfirmHost />
<ToastHost />

<style>
	.loading {
		height: 100vh;
		background: var(--bg);
	}

	.app-shell {
		display: flex;
		flex-direction: column;
		height: 100vh;
	}

	/* No padding: the screens lay themselves out edge to edge (file list
	   beside the lines). Simple screens wrap their content in `.page`. */
	main {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
		overflow: auto;
		background: var(--panel);
	}

	main:focus {
		outline: none;
	}
</style>
