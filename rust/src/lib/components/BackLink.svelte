<script lang="ts">
	// "← Review  Esc" at the top of the tool screens. Esc follows it, unless a
	// dialog is open (the dialog's own Esc closes it first).
	import { goto } from '$app/navigation';
	import { t } from '$lib/i18n';
	import { ROUTES } from '$lib/navigation';
	import { modalDepth } from '$lib/stores';
	import Kbd from './Kbd.svelte';

	function onkeydown(event: KeyboardEvent) {
		if (event.key !== 'Escape' || event.defaultPrevented || $modalDepth > 0) return;
		if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
		void goto(ROUTES.review);
	}
</script>

<svelte:window {onkeydown} />

<a class="btn ghost back" href={ROUTES.review}>
	<svg
		class="ico"
		viewBox="0 0 16 16"
		fill="none"
		stroke="currentColor"
		stroke-width="1.5"
		stroke-linecap="round"
		aria-hidden="true"><path d="M10 3.5L5.5 8 10 12.5" /></svg
	>
	{$t('project_setup.step_review')}
	<Kbd keys="Escape" />
</a>

<style>
	.back {
		align-self: flex-start;
		margin-left: -10px;
	}
</style>
