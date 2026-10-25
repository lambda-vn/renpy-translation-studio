<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type TestConnectionResult } from '$lib/api';
	import BackLink from '$lib/components/BackLink.svelte';
	import { confirmDialog } from '$lib/confirm';
	import { locale, t } from '$lib/i18n';
	import { errorText } from '$lib/messages';
	import { toast } from '$lib/toast';

	const MIN_BATCH = 1;
	const MAX_BATCH = 32;
	const DEFAULT_OLLAMA = 'http://localhost:11434';
	const LOCAL_HOSTS = ['localhost', '127.0.0.1', '[::1]', '::1'];

	type ProviderId = 'deepl' | 'ollama' | 'libretranslate';
	type Probe = { state: 'idle' | 'testing' | 'done'; ok: boolean; message: string };
	const idle = (): Probe => ({ state: 'idle', ok: false, message: '' });

	let loaded = $state(false);
	let error = $state('');
	let saving = $state(false);

	let deeplKey = $state('');
	let deeplHadKey = $state(false);
	let deepl = $state<Probe>(idle());

	let ollamaEndpoint = $state(DEFAULT_OLLAMA);
	let ollamaModel = $state('');
	let ollamaBatchSize = $state('');
	let ollamaModels = $state<string[]>([]);
	let ollamaBatchError = $state('');
	let ollama = $state<Probe>(idle());

	let ltUrl = $state('');
	let ltKey = $state('');
	let ltHadKey = $state(false);
	let lt = $state<Probe>(idle());
	let ltOpen = $state(false);

	let defaultProvider = $state<string | null>(null);

	const configured = $derived<ProviderId[]>([
		...(deeplKey.trim() || deeplHadKey ? (['deepl'] as const) : []),
		...(ollamaModel.trim() ? (['ollama'] as const) : []),
		...(ltUrl.trim() ? (['libretranslate'] as const) : [])
	]);

	const labels: Record<ProviderId, string> = {
		deepl: 'DeepL',
		ollama: 'Ollama',
		libretranslate: 'LibreTranslate'
	};

	const cleartextWarning = $derived.by(() => {
		if (!ltKey.trim() && !ltHadKey) return false;
		try {
			const url = new URL(ltUrl.trim());
			return url.protocol === 'http:' && !LOCAL_HOSTS.includes(url.hostname);
		} catch {
			return false;
		}
	});

	onMount(async () => {
		try {
			const s = await api.getSettings();
			deeplHadKey = s.deeplApiKeySet;
			ollamaEndpoint = s.ollamaEndpoint || DEFAULT_OLLAMA;
			ollamaModel = s.ollamaModel || '';
			ollamaBatchSize = s.ollamaBatchSize || '';
			ltUrl = s.libretranslateUrl || '';
			ltHadKey = s.libretranslateApiKeySet;
			ltOpen = Boolean(ltUrl);
			defaultProvider = s.defaultProvider;
			loaded = true;
		} catch (e) {
			error = String(e);
		}
	});

	function badge(id: ProviderId, probe: Probe): { cls: string; text: string } {
		if (probe.state === 'done') {
			return probe.ok
				? { cls: 'ok', text: $t('provider_config.llm_connection_ok') }
				: { cls: 'err', text: $t('provider_config.status_error') };
		}
		return configured.includes(id)
			? { cls: '', text: $t('provider_config.configured') }
			: { cls: '', text: $t('provider_config.status_unconfigured') };
	}

	async function testDeepl() {
		deepl = { state: 'testing', ok: false, message: $t('provider_config.testing') };
		try {
			const result = await api.testDeeplConnection(deeplKey.trim());
			deepl = {
				state: 'done',
				ok: result.ok,
				message: !result.ok
					? $t('translation.connection_failed')
					: result.charactersLeft === null
						? $t('provider_config.llm_connection_ok')
						: $t('translation.connection_ok', {
								chars: result.charactersLeft.toLocaleString($locale)
							})
			};
		} catch (e) {
			deepl = { state: 'done', ok: false, message: errorText($t, e) };
		}
	}

	async function testOllama() {
		ollama = { state: 'testing', ok: false, message: $t('provider_config.testing') };
		try {
			const result: TestConnectionResult = await api.testOllamaConnection(ollamaEndpoint.trim());
			ollamaModels = result.models;
			if (!result.ok) {
				ollama = {
					state: 'done',
					ok: false,
					message: $t('provider_config.ollama_connection_failed')
				};
			} else if (result.models.length === 0) {
				ollama = { state: 'done', ok: true, message: $t('provider_config.ollama_no_models') };
			} else {
				ollama = {
					state: 'done',
					ok: true,
					message: $t('provider_config.ollama_connection_ok', { n: result.models.length })
				};
			}
		} catch (e) {
			ollama = { state: 'done', ok: false, message: String(e) };
		}
	}

	async function testLibretranslate() {
		lt = { state: 'testing', ok: false, message: $t('provider_config.testing') };
		try {
			const result = await api.testLibretranslateConnection(ltUrl.trim(), ltKey.trim() || null);
			lt = {
				state: 'done',
				ok: result.ok,
				message: result.ok
					? $t('provider_config.llm_connection_ok')
					: $t('provider_config.ollama_connection_failed')
			};
		} catch (e) {
			lt = { state: 'done', ok: false, message: errorText($t, e) };
		}
	}

	async function removeKey(setting: 'deepl_api_key' | 'libretranslate_api_key', name: string) {
		const confirmed = await confirmDialog({
			title: $t('provider_config.key_remove_title', { provider: name }),
			message: $t('provider_config.key_remove_message'),
			confirmLabel: $t('provider_config.key_remove'),
			danger: true
		});
		if (!confirmed) return;
		try {
			await api.setSetting(setting, null);
			if (setting === 'deepl_api_key') {
				deeplHadKey = false;
				deepl = idle();
			} else {
				ltHadKey = false;
				lt = idle();
			}
		} catch (e) {
			error = String(e);
		}
	}

	function validBatchSize(text: string): boolean {
		if (!text) return true;
		if (!/^\d+$/.test(text)) return false;
		const n = Number(text);
		return n >= MIN_BATCH && n <= MAX_BATCH;
	}

	async function save() {
		error = '';
		ollamaBatchError = '';
		const batch = ollamaBatchSize.trim();
		if (!validBatchSize(batch)) {
			ollamaBatchError = $t('provider_config.ollama_batch_size_invalid', {
				min: MIN_BATCH,
				max: MAX_BATCH
			});
			document.getElementById('ol-batch')?.focus();
			return;
		}
		saving = true;
		try {
			if (deeplKey.trim()) await api.setSetting('deepl_api_key', deeplKey.trim());
			await api.setSetting('ollama_endpoint', ollamaEndpoint.trim() || DEFAULT_OLLAMA);
			await api.setSetting('ollama_model', ollamaModel.trim() || null);
			await api.setSetting('ollama_batch_size', batch || null);
			await api.setSetting('libretranslate_url', ltUrl.trim() || null);
			if (ltKey.trim()) await api.setSetting('libretranslate_api_key', ltKey.trim());
			const choice =
				defaultProvider && configured.includes(defaultProvider as ProviderId)
					? defaultProvider
					: (configured[0] ?? null);
			await api.setSetting('default_provider', choice);
			defaultProvider = choice;
			if (deeplKey.trim()) deeplHadKey = true;
			if (ltKey.trim()) ltHadKey = true;
			deeplKey = '';
			ltKey = '';
			toast.success($t('provider_config.saved'));
		} catch (e) {
			const message = String(e);
			error = /keyring/i.test(message) ? $t('provider_config.keyring_unavailable') : message;
		} finally {
			saving = false;
		}
	}
</script>

<svelte:head><title>{$t('provider_config.title')} — Ren'Py Translation Studio</title></svelte:head>

<div class="screen narrow">
	<BackLink />
	<div class="screen-head">
		<div>
			<h1>{$t('provider_config.title')}</h1>
			<p>{$t('provider_config.subtitle')}</p>
		</div>
	</div>

	{#if error}
		<p class="notice err" role="alert">{error}</p>
	{/if}

	{#if loaded}
		{#if configured.length > 1}
			<fieldset class="default">
				<legend>{$t('provider_config.default_label')}</legend>
				<div class="seg">
					{#each configured as id (id)}
						<label>
							<input
								type="radio"
								name="default-provider"
								value={id}
								checked={(defaultProvider ?? configured[0]) === id}
								onchange={() => (defaultProvider = id)}
							/>{labels[id]}
						</label>
					{/each}
				</div>
			</fieldset>
		{/if}

		<!-- DeepL -->
		<details open>
			<summary>
				<svg class="ico chev" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M6 3.5L10.5 8 6 12.5" /></svg>
				<span class="name">{$t('provider_config.deepl_title')}</span>
				{@render statusBadge(badge('deepl', deepl))}
			</summary>
			<div class="body">
				<div>
					<label class="lbl" for="dl-key">{$t('provider_config.api_key_label')}</label>
					<div class="row">
						<input
							id="dl-key"
							class="mono"
							type="password"
							autocomplete="off"
							placeholder={deeplHadKey
								? $t('provider_config.key_saved_placeholder')
								: $t('provider_config.api_key_hint')}
							bind:value={deeplKey}
							oninput={() => (deepl = idle())}
						/>
						{#if deeplHadKey}
							<button type="button" class="btn" onclick={() => removeKey('deepl_api_key', 'DeepL')}>
								{$t('provider_config.key_remove')}
							</button>
						{/if}
					</div>
					<p class="help">{$t('provider_config.key_stored')}</p>
				</div>
				<div class="row test">
					<button
						type="button"
						class="btn"
						disabled={(!deeplKey.trim() && !deeplHadKey) || deepl.state === 'testing'}
						onclick={testDeepl}
					>
						{$t('provider_config.test_connection')}
					</button>
				</div>
				{@render probeResult(deepl)}
			</div>
		</details>

		<!-- Ollama -->
		<details open>
			<summary>
				<svg class="ico chev" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M6 3.5L10.5 8 6 12.5" /></svg>
				<span class="name">{$t('provider_config.ollama_title')}</span>
				{@render statusBadge(badge('ollama', ollama))}
			</summary>
			<div class="body">
				<p class="note">{$t('provider_config.ollama_reliability_hint')}</p>
				<div class="grid">
					<div>
						<label class="lbl" for="ol-url">{$t('provider_config.ollama_endpoint_label')}</label>
						<input id="ol-url" class="mono" bind:value={ollamaEndpoint} oninput={() => (ollama = idle())} />
					</div>
					<div>
						<label class="lbl" for="ol-model">{$t('provider_config.ollama_model_label')}</label>
						<input
							id="ol-model"
							list="ol-models"
							autocomplete="off"
							placeholder={$t('provider_config.ollama_model_hint')}
							bind:value={ollamaModel}
						/>
						<datalist id="ol-models">
							{#each ollamaModels as model (model)}<option value={model}></option>{/each}
						</datalist>
					</div>
				</div>
				<div>
					<label class="lbl" for="ol-batch">{$t('provider_config.ollama_batch_size_label')}</label>
					<input
						id="ol-batch"
						class="mono batch"
						inputmode="numeric"
						placeholder="8"
						aria-describedby="ol-batch-help"
						aria-invalid={ollamaBatchError ? 'true' : undefined}
						bind:value={ollamaBatchSize}
						oninput={() => (ollamaBatchError = '')}
					/>
					<p class="help" id="ol-batch-help">{$t('provider_config.ollama_batch_size_hint')}</p>
					{#if ollamaBatchError}<p class="notice err" role="alert">{ollamaBatchError}</p>{/if}
				</div>
				<div class="row test">
					<button type="button" class="btn" disabled={ollama.state === 'testing'} onclick={testOllama}>
						{$t('provider_config.test_connection')}
					</button>
				</div>
				{@render probeResult(ollama)}
			</div>
		</details>

		<!-- LibreTranslate -->
		<details open={ltOpen}>
			<summary>
				<svg class="ico chev" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M6 3.5L10.5 8 6 12.5" /></svg>
				<span class="name">{$t('provider_config.libretranslate_title')}</span>
				{@render statusBadge(badge('libretranslate', lt))}
			</summary>
			<div class="body">
				<p class="note">{$t('provider_config.libretranslate_public_warning')}</p>
				<div class="grid">
					<div>
						<label class="lbl" for="lt-url">{$t('provider_config.libretranslate_url_label')}</label>
						<input
							id="lt-url"
							class="mono"
							placeholder={$t('provider_config.libretranslate_url_hint')}
							bind:value={ltUrl}
							oninput={() => (lt = idle())}
						/>
					</div>
					<div>
						<label class="lbl" for="lt-key">
							{$t('provider_config.libretranslate_api_key_label')}
							<span class="opt-note">· {$t('common.optional')}</span>
						</label>
						<div class="row">
							<input
								id="lt-key"
								class="mono"
								type="password"
								autocomplete="off"
								placeholder={ltHadKey ? $t('provider_config.key_saved_placeholder') : ''}
								bind:value={ltKey}
								oninput={() => (lt = idle())}
							/>
							{#if ltHadKey}
								<button type="button" class="btn" onclick={() => removeKey('libretranslate_api_key', 'LibreTranslate')}>
									{$t('provider_config.key_remove')}
								</button>
							{/if}
						</div>
						<p class="help">{$t('provider_config.libretranslate_api_key_hint')}</p>
					</div>
				</div>
				{#if cleartextWarning}
					<p class="notice warn" role="alert">
						<svg class="ico" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" aria-hidden="true"><path d="M8 1.8L14.8 13.8H1.2z" /><path d="M8 6.3v3.2M8 11.4v.1" stroke-linecap="round" /></svg>
						<span>{$t('provider_config.libretranslate_cleartext_warning')}</span>
					</p>
				{/if}
				<div class="row test">
					<button type="button" class="btn" disabled={!ltUrl.trim() || lt.state === 'testing'} onclick={testLibretranslate}>
						{$t('provider_config.test_connection')}
					</button>
				</div>
				{@render probeResult(lt)}
			</div>
		</details>

		<div class="save-row">
			<button type="button" class="btn primary" disabled={saving} onclick={save}>
				{$t('common.save')}
			</button>
		</div>
	{/if}
</div>

{#snippet statusBadge(b: { cls: string; text: string })}
	<span class="badge {b.cls}">
		{#if b.cls === 'ok'}
			<svg class="ico sm-ico" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.5" fill="currentColor" /><path d="M5 8.2l2 2 4-4.2" fill="none" stroke="var(--panel)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" /></svg>
		{:else if b.cls === 'err'}
			<svg class="ico sm-ico" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.8L14.8 13.8H1.2z" fill="currentColor" /><path d="M8 6.3v3.4M8 11.6v.1" stroke="var(--errWeak)" stroke-width="1.7" stroke-linecap="round" /></svg>
		{:else}
			<svg class="ico sm-ico" style="color: var(--s-none)" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.6" /></svg>
		{/if}
		{b.text}
	</span>
{/snippet}

{#snippet probeResult(probe: Probe)}
	<div class="result" role={probe.state === 'done' && !probe.ok ? 'alert' : 'status'}>
		{#if probe.message}
			<p class="notice" class:err={probe.state === 'done' && !probe.ok} class:ok={probe.state === 'done' && probe.ok}>
				{probe.message}
			</p>
		{/if}
	</div>
{/snippet}

<style>
	.narrow {
		max-width: 760px;
	}

	.default {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 14px;
		margin: 0 0 6px;
		padding: 0;
		border: 0;
	}
	.default legend {
		float: left;
		padding: 0;
		margin-right: 14px;
		font-size: 13px;
		font-weight: 500;
	}

	.seg {
		display: inline-flex;
		gap: 2px;
		padding: 2px;
		border: 1px solid var(--line2);
		border-radius: var(--r-md);
		background: var(--panel);
	}
	.seg label {
		position: relative;
		display: inline-flex;
		align-items: center;
		height: 28px;
		padding: 0 12px;
		border-radius: 7px;
		cursor: pointer;
		font-size: 13px;
		color: var(--ink2);
	}
	.seg label:has(input:checked) {
		background: var(--accWeak);
		color: var(--acc7);
		font-weight: 600;
	}
	.seg label:has(input:focus-visible) {
		outline: 2px solid var(--acc);
		outline-offset: 2px;
	}
	.seg input {
		position: absolute;
		opacity: 0;
		width: 1px;
		height: 1px;
	}

	details {
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: var(--r-lg);
	}
	summary {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 16px 18px;
		border-radius: var(--r-lg);
		cursor: pointer;
		list-style: none;
	}
	summary::-webkit-details-marker {
		display: none;
	}
	summary:hover {
		background: var(--hover);
	}
	.name {
		flex: 1;
		font-size: 14.5px;
		font-weight: 600;
	}
	.chev {
		color: var(--ink3);
		transition: transform 0.15s;
	}
	details[open] .chev {
		transform: rotate(90deg);
	}
	.sm-ico {
		width: 14px;
		height: 14px;
	}

	.body {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 4px 18px 18px 46px;
	}
	.grid {
		display: grid;
		grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
		gap: 12px;
	}
	@media (max-width: 640px) {
		.grid {
			grid-template-columns: minmax(0, 1fr);
		}
		.body {
			padding-left: 18px;
		}
	}
	.row {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.test {
		gap: 12px;
	}
	.batch {
		width: 120px;
	}
	.note {
		margin: 0;
		font-size: 12.5px;
		line-height: 1.55;
		color: var(--ink2);
	}
	.opt-note {
		font-weight: 400;
		color: var(--ink3);
	}
	.result .notice {
		padding: 8px 10px;
		font-size: 12.5px;
	}
	.result:not(:has(*)) {
		margin-top: -12px;
	}

	.save-row {
		display: flex;
		justify-content: flex-end;
		padding-top: 4px;
	}
</style>
