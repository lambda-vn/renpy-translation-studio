<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type TestConnectionResult } from '$lib/api';

	let loaded = $state(false);
	let error = $state('');
	let saving = $state(false);
	let saved = $state(false);

	let deeplApiKey = $state('');
	let deeplHadKey = $state(false);
	let deeplResult = $state<TestConnectionResult | null>(null);
	let deeplTesting = $state(false);

	let ollamaEndpoint = $state('http://localhost:11434');
	let ollamaModel = $state('');
	let ollamaBatchSize = $state('');
	let ollamaModels = $state<string[]>([]);
	let ollamaResult = $state<TestConnectionResult | null>(null);
	let ollamaTesting = $state(false);

	let libretranslateUrl = $state('');
	let libretranslateApiKey = $state('');
	let libretranslateHadKey = $state(false);
	let libretranslateResult = $state<TestConnectionResult | null>(null);
	let libretranslateTesting = $state(false);

	let verboseLogging = $state(false);

	onMount(async () => {
		try {
			const s = await api.getSettings();
			deeplHadKey = s.deeplApiKeySet;
			ollamaEndpoint = s.ollamaEndpoint || 'http://localhost:11434';
			ollamaModel = s.ollamaModel || '';
			ollamaBatchSize = s.ollamaBatchSize || '';
			libretranslateUrl = s.libretranslateUrl || '';
			libretranslateHadKey = s.libretranslateApiKeySet;
			verboseLogging = s.verboseLogging;
			loaded = true;
		} catch (e) {
			error = String(e);
		}
	});

	async function testDeepl() {
		deeplTesting = true;
		try {
			deeplResult = await api.testDeeplConnection(deeplApiKey);
		} catch (e) {
			deeplResult = { ok: false, detail: String(e), models: [] };
		} finally {
			deeplTesting = false;
		}
	}

	async function testOllama() {
		ollamaTesting = true;
		try {
			ollamaResult = await api.testOllamaConnection(ollamaEndpoint);
			ollamaModels = ollamaResult.models;
		} catch (e) {
			ollamaResult = { ok: false, detail: String(e), models: [] };
		} finally {
			ollamaTesting = false;
		}
	}

	async function testLibretranslate() {
		libretranslateTesting = true;
		try {
			libretranslateResult = await api.testLibretranslateConnection(
				libretranslateUrl,
				libretranslateApiKey || null
			);
		} catch (e) {
			libretranslateResult = { ok: false, detail: String(e), models: [] };
		} finally {
			libretranslateTesting = false;
		}
	}

	async function save() {
		saving = true;
		saved = false;
		error = '';
		try {
			if (deeplApiKey.trim()) await api.setSetting('deepl_api_key', deeplApiKey.trim());
			await api.setSetting('ollama_endpoint', ollamaEndpoint.trim() || null);
			await api.setSetting('ollama_model', ollamaModel.trim() || null);
			await api.setSetting('ollama_batch_size', ollamaBatchSize.trim() || null);
			await api.setSetting('libretranslate_url', libretranslateUrl.trim() || null);
			if (libretranslateApiKey.trim())
				await api.setSetting('libretranslate_api_key', libretranslateApiKey.trim());
			await api.setSetting('verbose_logging', verboseLogging ? 'true' : null);
			saved = true;
		} catch (e) {
			error = String(e);
		} finally {
			saving = false;
		}
	}
</script>

<h1>Translation providers</h1>

{#if error}
	<p class="error">{error}</p>
{/if}

{#if loaded}
	<section class="provider">
		<h2>DeepL</h2>
		<label>
			API key
			<input
				type="password"
				placeholder={deeplHadKey ? '••••••••  (leave blank to keep)' : 'API key'}
				bind:value={deeplApiKey}
			/>
		</label>
		<div class="row">
			<button disabled={deeplTesting} onclick={testDeepl}>
				{deeplTesting ? 'Testing…' : 'Test connection'}
			</button>
			{#if deeplResult}
				<span class={deeplResult.ok ? 'ok' : 'fail'}>
					{deeplResult.ok ? 'Connected' : 'Failed'}{deeplResult.detail ? ` — ${deeplResult.detail}` : ''}
				</span>
			{/if}
		</div>
	</section>

	<section class="provider">
		<h2>Ollama</h2>
		<p class="hint">A local LLM. Reliability depends on the model you pick.</p>
		<label>
			Endpoint
			<input type="text" bind:value={ollamaEndpoint} />
		</label>
		<label>
			Model
			{#if ollamaModels.length > 0}
				<select bind:value={ollamaModel}>
					<option value="">—</option>
					{#each ollamaModels as m (m)}
						<option value={m}>{m}</option>
					{/each}
				</select>
			{:else}
				<input type="text" placeholder="e.g. llama3.1" bind:value={ollamaModel} />
			{/if}
		</label>
		<label>
			Batch size (1–32, blank for default)
			<input type="text" bind:value={ollamaBatchSize} />
		</label>
		<div class="row">
			<button disabled={ollamaTesting} onclick={testOllama}>
				{ollamaTesting ? 'Testing…' : 'Test connection'}
			</button>
			{#if ollamaResult}
				<span class={ollamaResult.ok ? 'ok' : 'fail'}>
					{ollamaResult.ok ? `Connected — ${ollamaResult.models.length} model(s)` : 'Failed'}
				</span>
			{/if}
		</div>
	</section>

	<section class="provider">
		<h2>LibreTranslate</h2>
		<p class="hint">
			A public instance sends every line to a third party. Prefer a self-hosted one where
			possible.
		</p>
		<label>
			URL
			<input type="text" placeholder="https://libretranslate.example" bind:value={libretranslateUrl} />
		</label>
		<label>
			API key (optional)
			<input
				type="password"
				placeholder={libretranslateHadKey ? '••••••••  (leave blank to keep)' : ''}
				bind:value={libretranslateApiKey}
			/>
		</label>
		<div class="row">
			<button disabled={libretranslateTesting} onclick={testLibretranslate}>
				{libretranslateTesting ? 'Testing…' : 'Test connection'}
			</button>
			{#if libretranslateResult}
				<span class={libretranslateResult.ok ? 'ok' : 'fail'}>
					{libretranslateResult.ok ? 'Connected' : 'Failed'}
				</span>
			{/if}
		</div>
	</section>

	<section class="provider">
		<label class="checkbox">
			<input type="checkbox" bind:checked={verboseLogging} />
			Verbose logging (every provider request/response)
		</label>
	</section>

	<div class="row">
		<button class="primary" disabled={saving} onclick={save}>
			{saving ? 'Saving…' : 'Save'}
		</button>
		{#if saved}<span class="ok">Saved.</span>{/if}
	</div>
{/if}

<style>
	.provider {
		max-width: 520px;
		margin-bottom: 1.5rem;
		padding: 1rem;
		background: white;
		border: 1px solid #ddd;
		border-radius: 6px;
	}

	label {
		display: block;
		margin: 0.5rem 0;
		font-size: 0.9rem;
	}

	label.checkbox {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	input[type='text'],
	input[type='password'],
	select {
		display: block;
		width: 100%;
		margin-top: 0.2rem;
		padding: 0.4rem;
		border: 1px solid #ccc;
		border-radius: 4px;
	}

	.hint {
		color: #666;
		font-size: 0.85rem;
	}

	.row {
		display: flex;
		align-items: center;
		gap: 0.7rem;
		margin-top: 0.5rem;
	}

	button {
		padding: 0.4rem 0.9rem;
		border: 1px solid #ccc;
		border-radius: 4px;
		background: #f4f4f4;
	}

	button.primary {
		background: #2b6cb0;
		color: white;
		border: none;
	}

	.ok {
		color: #087f23;
	}

	.fail {
		color: #b00020;
	}

	.error {
		color: #b00020;
	}
</style>
