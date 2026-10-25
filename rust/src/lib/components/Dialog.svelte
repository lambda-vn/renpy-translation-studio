<script lang="ts">
	// Modal dialog on the native <dialog>: focus trap, inert page, Esc and the
	// backdrop come from the browser.
	//
	//   <Dialog bind:open title={$t('help.title')}>
	//     body...
	//     {#snippet actions()}<button class="btn primary" onclick={...}>OK</button>{/snippet}
	//   </Dialog>
	//
	// The body and actions only exist while open, so `autofocus` on an element
	// inside picks the initial focus (otherwise: the close button).
	import type { Snippet } from 'svelte';
	import { t } from '$lib/i18n';
	import { modalDepth } from '$lib/stores';

	interface Props {
		open?: boolean;
		title: string;
		/** "alertdialog" for confirmations that interrupt the flow. */
		role?: 'dialog' | 'alertdialog';
		size?: 'sm' | 'md' | 'lg';
		/** Called after every close (Esc, button, or `open = false`). */
		onclose?: () => void;
		children: Snippet;
		/** Footer buttons. */
		actions?: Snippet;
	}

	let {
		open = $bindable(false),
		title,
		role = 'dialog',
		size = 'md',
		onclose,
		children,
		actions
	}: Props = $props();

	const uid = $props.id();
	const titleId = `dialog-title-${uid}`;

	let dialog: HTMLDialogElement | undefined = $state();
	let opener: HTMLElement | null = null;
	let shown = false;

	$effect(() => {
		if (!dialog) return;
		if (open && !dialog.open) {
			opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
			shown = true;
			dialog.showModal();
		} else if (!open && dialog.open) {
			dialog.close();
			// The native `close` event is queued as a task and arrives late; finish
			// now so callers (confirmDialog) never wait on it. `shown` makes the
			// late event a no-op.
			finish();
		}
	});

	$effect(() => {
		if (!open) return;
		modalDepth.update((n) => n + 1);
		return () => modalDepth.update((n) => n - 1);
	});

	function finish() {
		if (!shown) return;
		shown = false;
		open = false;
		// Browsers already return focus to the opener; this covers the ones
		// that don't, and openers that were re-rendered in between.
		if (opener?.isConnected) opener.focus();
		opener = null;
		onclose?.();
	}
</script>

<dialog
	bind:this={dialog}
	class="dlg {size}"
	{role}
	aria-labelledby={titleId}
	onclose={finish}
>
	{#if open}
		<div class="dh">
			<h2 id={titleId}>{title}</h2>
			<button
				type="button"
				class="btn ghost icon"
				aria-label="{$t('common.close')} ({$t('help.key_escape')})"
				onclick={() => dialog?.close()}
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
		<div class="db">
			{@render children()}
		</div>
		{#if actions}
			<div class="df">
				{@render actions()}
			</div>
		{/if}
	{/if}
</dialog>

<style>
	.dlg {
		padding: 0;
		margin: auto;
		border: 1px solid var(--line);
		border-radius: var(--r-lg);
		background: var(--panel);
		color: var(--ink);
		box-shadow: var(--shadow-dialog);
		max-width: calc(100vw - 32px);
		max-height: calc(100vh - 48px);
		overflow: hidden;
	}

	.dlg[open] {
		display: flex;
		flex-direction: column;
	}

	.dlg.sm {
		width: 400px;
	}
	.dlg.md {
		width: 480px;
	}
	.dlg.lg {
		width: 620px;
	}

	.dlg::backdrop {
		background: var(--backdrop);
	}

	.dh {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 14px 12px 10px 18px;
		flex: none;
	}

	h2 {
		margin: 0;
		flex: 1;
		font-size: 15px;
		font-weight: 700;
	}

	.db {
		padding: 4px 18px 16px;
		display: flex;
		flex-direction: column;
		gap: 14px;
		overflow: auto;
		min-height: 0;
	}

	.df {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 12px 18px;
		border-top: 1px solid var(--line);
		background: var(--bg);
		flex: none;
	}
</style>
