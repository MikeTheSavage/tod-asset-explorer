import React from 'react'

// Shown when the asset folder is empty or missing: explains how to extract from your own game.
export default function EmptyState({ meta, error }) {
  const root = meta?.assetsRoot || 'assets'
  return (
    <div className="emptystate">
      <div className="card">
        <h2>No assets yet</h2>
        {error ? (
          <p>The viewer could not load its asset list ({error}). Start it with <code>serve.py</code>,
            <code>run.bat</code> / <code>run.sh</code> or <code>npm run dev</code>, not by opening the HTML file directly.</p>
        ) : (
          <p>No <code>.glb</code> files were found in <code>{root}</code>{meta?.assetsRootExists === false ? ' (the folder does not exist yet)' : ''}.</p>
        )}
        <p>This tool ships without any game content. Extract the models from <b>your own copy</b> of
          Total Overdose (for example the GOG version):</p>
        <pre>python extractor/tod_extract.py --game "C:\GOG Games\Total Overdose" --out assets</pre>
        <p>Point <code>--game</code> at the folder that contains <code>TOD.exe</code> and <code>blocks.naz</code>.
          It takes about a minute. Then reload this page.</p>
        <p className="hint">Using a different folder? Start the viewer with <code>--assets &lt;dir&gt;</code> or set
          the <code>TOD_ASSETS</code> environment variable. On Windows, <code>run.bat</code> does all of this for you.</p>
      </div>
    </div>
  )
}
