<script lang="ts">
	// File title, automatic translation, the "More actions" menu and the
	// write-to-.rpy button with the count of lines not written yet.
	import ContextMenu, { type MenuEntry } from '$lib/components/ContextMenu.svelte';
	import Kbd from '$lib/components/Kbd.svelte';
	import { t } from '$lib/i18n';

	interface Props {
		name: string;
		dir: string;
		validated: number;
		total: number;
		unwritten: number;
		saving: boolean;
		jobRunning: boolean;
		moreItems: MenuEntry[];
		onautotranslate: () => void;
		onsave: () => void;
	}

	let {
		name,
		dir,
		validated,
		total,
		unwritten,
		saving,
		jobRunning,
		moreItems,
		onautotranslate,
		onsave
	}: Props = $props();

	let menuOpen = $state(false);
	let wasOpen = false;
	let moreButton: HTMLButtonElement | undefined = $state();
</script>

<div class="toolbar">
	<div class="title">
		<h1 title={name}>{name}</h1>
		<p class="sub">
			{#if dir}{dir} ·{' '}{/if}<span class="mono">{validated} / {total}</span>{' '}{$t('review.validated')}
		</p>
	</div>
	<div class="actions">
		<button type="button" class="btn" disabled={jobRunning} onclick={onautotranslate}>
			<svg
				class="ico"
				viewBox="0 0 16 16"
				fill="none"
				stroke="currentColor"
				stroke-width="1.4"
				stroke-linejoin="round"
				aria-hidden="true"><path d="M9 1.8L3.8 9h4l-1 5.2L12.2 7h-4z" /></svg
			>
			{$t('translation.translate_automatic')}…
		</button>
		<button
			type="button"
			class="btn"
			bind:this={moreButton}
			aria-haspopup="menu"
			aria-expanded={menuOpen}
			onpointerdown={() => (wasOpen = menuOpen)}
			onclick={() => {
				menuOpen = !wasOpen;
				wasOpen = false;
			}}
		>
			{$t('review.more_actions')}
			<svg
				class="ico"
				viewBox="0 0 16 16"
				fill="none"
				stroke="currentColor"
				stroke-width="1.5"
				stroke-linecap="round"
				aria-hidden="true"><path d="M4 6.5L8 10.5 12 6.5" /></svg
			>
		</button>
		<span class="divider" aria-hidden="true"></span>
		<p id="unwritten" class="unwritten" class:pending={unwritten > 0}>
			{#if unwritten > 0}
				<svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true"
					><circle cx="4" cy="4" r="4" fill="currentColor" /></svg
				>
				<span>{$t('review.sync_pending', { n: unwritten })}</span>
			{:else}
				<span>{$t('review.sync_ok')}</span>
			{/if}
		</p>
		<button
			type="button"
			class="btn primary"
			aria-describedby="unwritten"
			disabled={saving}
			onclick={onsave}
		>
			<svg
				class="ico"
				viewBox="0 0 16 16"
				fill="none"
				stroke="currentColor"
				stroke-width="1.4"
				stroke-linejoin="round"
				aria-hidden="true"
				><path d="M3 2.5h7.8l2.7 2.7v8.3H3z" /><path d="M5.5 2.5v3h4.5v-3M5 13.5v-4h6v4" /></svg
			>
			{$t('review.write_rpy')}
			<Kbd shortcut="save" />
		</button>
	</div>
</div>

<ContextMenu
	bind:open={menuOpen}
	label={$t('review.more_actions')}
	items={moreItems}
	anchor={moreButton}
/>

<style>
	.toolbar {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-start;
		gap: 12px 20px;
	}

	.title {
		flex: 1 1 240px;
		min-width: 0;
	}

	h1 {
		margin: 0;
		font-size: 21px;
		font-weight: 700;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.sub {
		margin: 4px 0 0;
		font-size: 13px;
		color: var(--ink3);
	}

	.actions {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}

	.divider {
		width: 1px;
		height: 22px;
		background: var(--line);
		margin: 0 6px;
	}

	.unwritten {
		margin: 0;
		font-size: 13px;
		color: var(--ink3);
		display: inline-flex;
		align-items: center;
		gap: 6px;
		white-space: nowrap;
	}

	.unwritten.pending {
		color: var(--warn);
	}
</style>
