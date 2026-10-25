<script lang="ts">
	// One toast. role="status" is polite; errors use role="alert". The timer
	// stops while the pointer or the keyboard focus is on the toast, so it
	// can be read (or its button reached) without racing the clock.
	import { t } from '$lib/i18n';
	import { dismissToast, type ToastItem } from '$lib/toast';
	import StatusGlyph from './StatusGlyph.svelte';

	let { item }: { item: ToastItem } = $props();

	let paused = $state(false);

	$effect(() => {
		if (paused || item.duration <= 0) return;
		const timer = setTimeout(() => dismissToast(item.id), item.duration);
		return () => clearTimeout(timer);
	});

	function runAction() {
		item.action?.run();
		dismissToast(item.id);
	}
</script>

<div
	class="toast"
	role={item.kind === 'error' ? 'alert' : 'status'}
	onmouseenter={() => (paused = true)}
	onmouseleave={() => (paused = false)}
	onfocusin={() => (paused = true)}
	onfocusout={() => (paused = false)}
>
	{#if item.kind === 'success'}
		<StatusGlyph kind="human_validated" size={16} />
	{:else if item.kind === 'error'}
		<StatusGlyph kind="error" size={16} />
	{:else}
		<svg
			class="info"
			width="16"
			height="16"
			viewBox="0 0 16 16"
			fill="none"
			stroke="currentColor"
			stroke-width="1.5"
			stroke-linecap="round"
			aria-hidden="true"
			focusable="false"
		>
			<circle cx="8" cy="8" r="6.25" />
			<path d="M8 7.2v3.6M8 5v.1" />
		</svg>
	{/if}
	<span class="message">{item.message}</span>
	{#if item.action}
		<button type="button" class="btn ghost sm" onclick={runAction}>{item.action.label}</button>
	{/if}
	<button
		type="button"
		class="btn ghost sm icon"
		aria-label={$t('common.close')}
		onclick={() => dismissToast(item.id)}
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
</div>

<style>
	.toast {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 8px 8px 12px;
		min-width: 260px;
		max-width: 420px;
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: var(--r-md);
		box-shadow: var(--shadow-pop);
		font-size: 13.5px;
	}

	.message {
		flex: 1;
		min-width: 0;
		overflow-wrap: anywhere;
	}

	.info {
		color: var(--acc);
		flex: none;
	}

	.icon {
		width: 28px;
		padding: 0;
	}
</style>
