<script lang="ts">
	// Bottom-right stack of toasts. Mount once, in the layout.
	import { toasts } from '$lib/toast';
	import Toast from './Toast.svelte';
</script>

<div class="toasts">
	{#each $toasts as item (item.id)}
		<Toast {item} />
	{/each}
</div>

<style>
	.toasts {
		position: fixed;
		right: 20px;
		bottom: 20px;
		z-index: 900;
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 8px;
		pointer-events: none;
	}

	.toasts > :global(*) {
		pointer-events: auto;
	}
</style>
