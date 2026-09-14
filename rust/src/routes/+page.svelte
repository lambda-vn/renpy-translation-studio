<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";

  type TranslationUnit = {
    block_id: string;
    source_file: string;
    source_line: number;
    source_text: string;
    translated_text: string;
    status: string;
  };

  type ProjectSummary = {
    total: number;
    human_validated: number;
    units: TranslationUnit[];
  };

  let dbPath = $state("");
  let summary = $state<ProjectSummary | null>(null);
  let error = $state("");

  async function openProject(event: Event) {
    event.preventDefault();
    error = "";
    summary = null;
    try {
      summary = await invoke<ProjectSummary>("open_project", {
        dbPath,
        limit: 50,
      });
    } catch (e) {
      error = String(e);
    }
  }
</script>

<main class="container">
  <h1>Cap sur Rust — spike alpha.1</h1>
  <p class="hint">
    Colle le chemin d'un <code>translations.db</code> produit par la 1.0.0
    Python (dans <code>&lt;jeu&gt;/.rts/translations.db</code>).
  </p>

  <form class="row" onsubmit={openProject}>
    <input
      placeholder="D:\VN\Games\the_question-rts\.rts\translations.db"
      bind:value={dbPath}
    />
    <button type="submit">Ouvrir</button>
  </form>

  {#if error}
    <p class="error">{error}</p>
  {/if}

  {#if summary}
    <p class="summary">
      {summary.total} unités, {summary.human_validated} validées
    </p>
    <table>
      <thead>
        <tr>
          <th>Fichier</th>
          <th>Ligne</th>
          <th>Statut</th>
          <th>Source</th>
          <th>Traduction</th>
        </tr>
      </thead>
      <tbody>
        {#each summary.units as unit (unit.block_id)}
          <tr>
            <td>{unit.source_file}</td>
            <td>{unit.source_line}</td>
            <td>{unit.status}</td>
            <td>{unit.source_text}</td>
            <td>{unit.translated_text}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</main>

<style>
  :root {
    font-family:
      Inter,
      Avenir,
      Helvetica,
      Arial,
      sans-serif;
    color: #0f0f0f;
    background-color: #f6f6f6;
  }

  .container {
    margin: 0 auto;
    max-width: 1000px;
    padding: 2rem 1.5rem;
  }

  .hint {
    color: #555;
  }

  .row {
    display: flex;
    gap: 0.5rem;
  }

  input {
    flex: 1;
    padding: 0.5em 0.8em;
    border: 1px solid #ccc;
    border-radius: 6px;
  }

  button {
    padding: 0.5em 1.2em;
    border-radius: 6px;
    border: 1px solid transparent;
    background-color: #396cd8;
    color: white;
    cursor: pointer;
  }

  .error {
    color: #c0392b;
  }

  .summary {
    font-weight: 600;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 1rem;
    font-size: 0.9rem;
  }

  th,
  td {
    text-align: left;
    padding: 0.4em 0.6em;
    border-bottom: 1px solid #ddd;
  }

  @media (prefers-color-scheme: dark) {
    :root {
      color: #f6f6f6;
      background-color: #2f2f2f;
    }

    .hint {
      color: #bbb;
    }

    input {
      background-color: #1c1c1c;
      color: #f6f6f6;
      border-color: #444;
    }

    th,
    td {
      border-color: #444;
    }
  }
</style>
