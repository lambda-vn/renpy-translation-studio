<script lang="ts">
	// Renders the requests made through confirmDialog(). Mount once, in the layout.
	import { pendingConfirms, type ConfirmRequest } from '$lib/confirm';
	import { t } from '$lib/i18n';
	import Dialog from './Dialog.svelte';

	const current: ConfirmRequest | undefined = $derived($pendingConfirms[0]);

	let open = $state(false);
	let answer = false;
	let shown: ConfirmRequest | undefined;

	// Each new request opens the dialog once. Comparing with the request
	// already shown (not with `open`) keeps the effect from reopening the
	// dialog the instant `choose()` closes it.
	$effect(() => {
		if (current && current !== shown) {
			shown = current;
			answer = false;
			open = true;
		}
	});

	function choose(confirmed: boolean) {
		answer = confirmed;
		open = false;
	}

	function settle() {
		const request = current;
		if (!request) return;
		pendingConfirms.update((queue) => queue.slice(1));
		request.resolve(answer);
	}
</script>

{#if current}
	<Dialog bind:open title={current.title} role="alertdialog" size="sm" onclose={settle}>
		{#if current.message}
			<p class="message">{current.message}</p>
		{/if}
		{#snippet actions()}
			<!-- Danger: focus lands on Cancel, so a stray Enter doesn't destroy anything. -->
			<!-- svelte-ignore a11y_autofocus -->
			<button
				type="button"
				class="btn"
				autofocus={current?.danger}
				onclick={() => choose(false)}
			>
				{current?.cancelLabel ?? $t('common.cancel')}
			</button>
			<!-- svelte-ignore a11y_autofocus -->
			<button
				type="button"
				class="btn"
				class:danger={current?.danger}
				class:primary={!current?.danger}
				autofocus={!current?.danger}
				onclick={() => choose(true)}
			>
				{current?.confirmLabel ?? $t('common.confirm')}
			</button>
		{/snippet}
	</Dialog>
{/if}

<style>
	.message {
		margin: 0;
		font-size: 13.5px;
		line-height: 1.5;
		color: var(--ink2);
		white-space: pre-line;
	}
</style>
