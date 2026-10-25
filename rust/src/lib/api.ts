// Typed wrappers around the Tauri commands in `src-tauri/src/commands/`.
// One function per command; keeps every `invoke()` call and its argument
// shape in a single place instead of scattered through the routes.

import { invoke } from '@tauri-apps/api/core';

/** What a recent-project card shows, read from the game's own database. */
export interface ProjectResume {
	sourceLanguage: string;
	targetLanguage: string;
	total: number;
	validated: number;
	aiSuggested: number;
	imported: number;
}

export interface ProjectEntry {
	name: string;
	path: string;
	ready: boolean;
	/** null when the project cannot be resumed (no units, no target language, tl/ gone). */
	resume: ProjectResume | null;
}

export interface ProjectInfo {
	path: string;
	gameName: string;
	sourceLanguage: string;
	targetLanguage: string;
	byStatus: Record<string, number>;
}

export interface FileEntry {
	sourceFile: string;
	/** Absolute path on disk, for "copy path". */
	path: string;
	total: number;
	validated: number;
	aiSuggested: number;
	draft: number;
	imported: number;
}

export interface UnitPayload {
	blockId: string;
	sourceFile: string;
	sourceLine: number;
	speaker: string | null;
	sourceText: string;
	translatedText: string;
	status: string;
	needsReview: boolean;
	note: string | null;
}

export interface ListUnitsArgs {
	sourceFile: string;
	status?: string | null;
	search?: string;
	speaker?: string | null;
	needsReview?: boolean;
	/** The "In error" filter: translated lines a blocking quality check refuses. */
	errorsOnly?: boolean;
	page?: number;
	pageSize?: number;
}

export interface DuplicateStats {
	/** Every occurrence of the text, the displayed line included. */
	total: number;
	/** Those outside the file being displayed. */
	otherFiles: number;
}

export interface ListUnitsResult {
	units: UnitPayload[];
	/** Keyed by blockId, only for lines whose source text occurs elsewhere. */
	duplicates: Record<string, DuplicateStats>;
	total: number;
	page: number;
	pageSize: number;
}

export interface QualityIssuePayload {
	kind: string;
	detail: string;
}

export interface ValidateResult {
	unit: UnitPayload | null;
	blockingIssues: QualityIssuePayload[];
	warnings: QualityIssuePayload[];
	/** Other not-yet-validated lines sharing the source text (offer to spread). */
	duplicates: number;
}

export interface PropagateResult {
	unit: UnitPayload | null;
	blockingIssues: QualityIssuePayload[];
	warnings: QualityIssuePayload[];
	/** blockIds of the other lines that received the translation. */
	propagated: string[];
}

/** unvalidated = suggestions, drafts, imports; all = validated lines too. */
export type ClearScope = 'unvalidated' | 'ai_suggested' | 'all';

export interface ClearArgs {
	/** Relative path of one file; omit for the whole project. */
	sourceFile?: string | null;
	scope?: ClearScope | null;
}

export interface SpeakerEntry {
	variable: string;
	label: string;
}

export interface ProgressPayload {
	lines: number;
	validatedLines: number;
	words: number;
	validatedWords: number;
}

export interface FailingFile {
	sourceFile: string;
	count: number;
}

export interface SyncPayload {
	neverSaved: boolean;
	unsavedUnits: number;
	externallyModified: boolean;
	inSync: boolean;
}

export interface ExportInfo {
	gameName: string;
	zipFileName: string;
	total: number;
	untranslated: number;
	/** Worst file first. */
	failing: FailingFile[];
	/** null when the tl/ folder cannot be compared (no target language). */
	sync: SyncPayload | null;
}

export interface MemoryPair {
	sourceLanguage: string;
	targetLanguage: string;
	entries: number;
}

export interface UnitTranslation {
	unit: UnitPayload;
	failed: boolean;
	error: string | null;
	events: string[];
}

export interface CharacterEntry {
	variable: string;
	displayName: string;
	notes: string | null;
}

export interface SettingsPayload {
	locale: string | null;
	theme: string | null;
	defaultProvider: string | null;
	deeplApiKeySet: boolean;
	ollamaEndpoint: string | null;
	ollamaModel: string | null;
	ollamaBatchSize: string | null;
	libretranslateUrl: string | null;
	libretranslateApiKeySet: boolean;
	verboseLogging: boolean;
	sdkPath: string | null;
	availableProviders: string[];
	availableLlmProviders: string[];
}

export interface TestConnectionResult {
	ok: boolean;
	detail: string | null;
	models: string[];
}

export interface StartJobArgs {
	providerId: string;
	/** filter = the lines the review filters select, validated ones excluded. */
	scope: 'project' | 'file' | 'filter';
	sourceFile?: string | null;
	/** project/file scopes: also retranslate existing drafts. */
	includeDrafts?: boolean;
	/** Required by scope "filter". */
	filter?: ListUnitsArgs | null;
}

export type JobEventPayload =
	| {
			kind: 'progress';
			total: number;
			done: number;
			failed: number;
			running: boolean;
			finished: boolean;
			error: string | null;
	  }
	| { kind: 'chunkPersisted' }
	| { kind: 'event'; message: string };

export interface LanguageEntry {
	code: string;
	label: string;
}

export interface GameInspection {
	valid: boolean;
	gameName: string;
	needsSdk: boolean;
	hasExistingTl: boolean;
	hasDatabase: boolean;
	existingLanguages: string[];
}

export type ExtractMode = 'keep' | 'update' | 'reset';

export type ExtractionStage = 'archiving' | 'unpacking' | 'running' | 'parsing' | 'syncing';

export interface ExtractionReport {
	units: number;
	moved: number;
	obsolete: number;
	discardedSources: string[];
	repaired: number;
}

export interface ExtractionOutcome {
	project: ProjectInfo;
	report: ExtractionReport;
}

/** What a failed extraction carries; `code` selects the localized message. */
export interface ExtractionFailure {
	code: string;
	message: string;
	detail: string | null;
	params: Record<string, string>;
}

export interface ImportPreview {
	applicable: number;
	unknown: number;
	stale: number;
	empty: number;
	protected: number;
	flagged: number;
}

export interface ImportOutcome {
	applied: number;
	plan: ImportPreview;
}

export const api = {
	listRecentProjects: () => invoke<ProjectEntry[]>('list_recent_projects'),
	openProject: (path: string) => invoke<ProjectInfo>('open_project', { path }),
	/** Drop the game from the recent list; touches nothing on disk. */
	forgetProject: (path: string) => invoke<void>('forget_project', { path }),
	/** Delete the game's .rts/ (translations, backups) and forget it. Irreversible: confirm first. */
	deleteProjectData: (path: string) => invoke<void>('delete_project_data', { path }),
	currentProject: () => invoke<ProjectInfo | null>('current_project'),
	listLanguages: () => invoke<LanguageEntry[]>('list_languages'),
	inspectGame: (path: string, targetLanguage: string) =>
		invoke<GameInspection>('inspect_game', { path, targetLanguage }),
	extractProject: (args: {
		path: string;
		sourceLanguage: string;
		targetLanguage: string;
		mode: ExtractMode;
	}) => invoke<ExtractionOutcome>('extract_project', args),

	startLive: () => invoke<void>('start_live'),
	stopLive: () => invoke<void>('stop_live'),
	getUnits: (blockIds: string[]) => invoke<UnitPayload[]>('get_units', { blockIds }),
	listFiles: () => invoke<FileEntry[]>('list_files'),
	listUnits: (args: ListUnitsArgs) => invoke<ListUnitsResult>('list_units', { args }),
	/** Per-file match counts (relative paths) for a search/speaker/flag under a status. */
	countMatches: (args: {
		search: string;
		status: string | null;
		speaker: string | null;
		needsReview: boolean;
	}) => invoke<Record<string, number>>('count_matches', args),
	listSpeakers: () => invoke<SpeakerEntry[]>('list_speakers'),
	projectProgress: () => invoke<ProgressPayload>('project_progress'),
	/** The lines around one line, itself included (default radius 2). */
	getContext: (blockId: string, radius?: number) =>
		invoke<UnitPayload[]>('get_context', { blockId, radius: radius ?? null }),
	saveDraft: (blockId: string, translatedText: string) =>
		invoke<UnitPayload>('save_draft', { blockId, translatedText }),
	validateUnit: (blockId: string, translatedText: string) =>
		invoke<ValidateResult>('validate_unit', { blockId, translatedText }),
	/** Ctrl+Shift+Enter: validate, then copy to every identical, non-validated line. */
	validateAndPropagate: (blockId: string, translatedText: string) =>
		invoke<PropagateResult>('validate_and_propagate', { blockId, translatedText }),
	/** Toast action after a plain validation; the line must be validated. Returns the lines written. */
	spreadToDuplicates: (blockId: string) => invoke<string[]>('spread_to_duplicates', { blockId }),
	/** Bulk clear; returns how many lines were cleared. Flags and notes are kept. Confirm first. */
	clearTranslations: (args: ClearArgs) => invoke<number>('clear_translations', { args }),
	/** Row "Erase": back to not_translated with an empty text (same as saveDraft with ''). */
	clearUnit: (blockId: string) =>
		invoke<UnitPayload>('save_draft', { blockId, translatedText: '' }),
	/** "N lines not written to .rpy". */
	unwrittenCount: () => invoke<number>('unwritten_count'),
	/** Show the file in the OS file manager. Copying the path is up to the frontend (FileEntry.path). */
	revealFile: (sourceFile: string) => invoke<void>('reveal_file', { sourceFile }),
	setNeedsReview: (blockId: string, needsReview: boolean) =>
		invoke<UnitPayload>('set_needs_review', { blockId, needsReview }),
	setNote: (blockId: string, note: string) => invoke<UnitPayload>('set_note', { blockId, note }),

	startTranslationJob: (args: StartJobArgs) => invoke<void>('start_translation_job', { args }),
	/** Translate one line; resolves when the job ends. A validated line is left unchanged. */
	translateUnit: (providerId: string, blockId: string) =>
		invoke<UnitTranslation>('translate_unit', { providerId, blockId }),
	cancelTranslationJob: () => invoke<void>('cancel_translation_job'),
	isTranslationJobRunning: () => invoke<boolean>('is_translation_job_running'),

	getSettings: () => invoke<SettingsPayload>('get_settings'),
	setSetting: (key: string, value: string | null) => invoke<void>('set_setting', { key, value }),
	/** true until the onboarding is finished (no settings file existed at startup). */
	isFirstLaunch: () => invoke<boolean>('is_first_launch'),
	validateSdkPath: (path: string) => invoke<boolean>('validate_sdk_path', { path }),
	/** Refuses an SDK path that is not a Ren'Py launcher; writes locale (+ sdk_path). */
	completeOnboarding: (locale: string, sdkPath: string | null) =>
		invoke<void>('complete_onboarding', { locale, sdkPath }),
	memoryStats: () => invoke<MemoryPair[]>('memory_stats'),
	/** Forget one language pair of the translation memory; returns entries removed. Confirm first. */
	forgetMemory: (sourceLanguage: string, targetLanguage: string) =>
		invoke<number>('forget_memory', { sourceLanguage, targetLanguage }),
	testDeeplConnection: (apiKey: string) =>
		invoke<TestConnectionResult>('test_deepl_connection', { apiKey }),
	testOllamaConnection: (endpoint: string) =>
		invoke<TestConnectionResult>('test_ollama_connection', { endpoint }),
	testLibretranslateConnection: (url: string, apiKey: string | null) =>
		invoke<TestConnectionResult>('test_libretranslate_connection', { url, apiKey }),

	listCharacters: () => invoke<CharacterEntry[]>('list_characters'),
	upsertCharacter: (variable: string, displayName: string, notes: string | null) =>
		invoke<CharacterEntry[]>('upsert_character', { variable, displayName, notes }),
	detectCharacters: () => invoke<CharacterEntry[]>('detect_characters'),
	deleteCharacter: (variable: string) =>
		invoke<CharacterEntry[]>('delete_character', { variable }),

	getUniverseSummary: () => invoke<string | null>('get_universe_summary'),
	setUniverseSummary: (summary: string) => invoke<void>('set_universe_summary', { summary }),
	generateUniverseSummary: () => invoke<string>('generate_universe_summary'),

	exportInterchange: (path: string, sourceFile: string | null) =>
		invoke<number>('export_interchange', { path, sourceFile }),
	planInterchangeImport: (path: string) =>
		invoke<ImportPreview>('plan_interchange_import', { path }),
	applyInterchangeImport: (path: string) =>
		invoke<ImportOutcome>('apply_interchange_import', { path }),
	fillFromMemory: () => invoke<number>('fill_from_memory'),

	/** Writes every unit to the .rpy files and records the save; returns lines holding a translation. */
	saveProject: () => invoke<number>('save_project'),
	exportInfo: () => invoke<ExportInfo>('export_info'),
	zipFileName: (gameName: string) => invoke<string>('zip_file_name', { gameName }),
	/** gameName = the zip's top folder as edited on screen; omit for the resolved name. */
	exportProject: (outputPath: string, gameName?: string | null) =>
		invoke<void>('export_project', { outputPath, gameName: gameName ?? null })
};
