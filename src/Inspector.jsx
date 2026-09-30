import React from 'react'

export default function Inspector({ entry, info, opts, setOpts, anim, setAnim, onSeek, onStep, onFit }) {
  const clips = info?.clips?.length ? info.clips : (entry?.clips || [])
  const hasAnim = clips.length > 0

  return (
    <div className="inspector">
      {!entry && <div className="hint">Select a model from the list to preview it.</div>}
      {entry && (
        <>
          <div className="section">
            <h3>Model</h3>
            <div className="kv"><span>file</span><span title={entry.file} style={{ maxWidth: 170, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{entry.file}</span></div>
            <div className="kv"><span>group</span><span>{entry.group}</span></div>
            <div className="kv"><span>map</span><span>{entry.map}</span></div>
            <div className="kv"><span>meshes</span><span>{info?.meshes ?? entry.meshes}</span></div>
            <div className="kv"><span>materials</span><span>{info?.materials ?? entry.materials}</span></div>
            <div className="kv"><span>vertices</span><span>{info?.verts != null ? info.verts.toLocaleString() : '—'}</span></div>
            <div className="kv"><span>textures</span><span>{entry.images}</span></div>
            <div className="kv"><span>rig / skin</span><span>{entry.skins > 0 || info?.hasSkeleton ? 'yes' : 'no'}</span></div>
            <div className="kv"><span>clips</span><span>{clips.length}</span></div>
            <div className="kv"><span>size</span><span>{entry.kb} KB</span></div>
          </div>

          <div className="section">
            <h3>Render</h3>
            <div className="row"><label>Wireframe</label><input type="checkbox" checked={opts.wireframe} onChange={e => setOpts(o => ({ ...o, wireframe: e.target.checked }))} /></div>
            <div className="row"><label>Double-sided</label><input type="checkbox" checked={opts.doubleSide} onChange={e => setOpts(o => ({ ...o, doubleSide: e.target.checked }))} /></div>
            <div className="row"><label>Grid</label><input type="checkbox" checked={opts.grid} onChange={e => setOpts(o => ({ ...o, grid: e.target.checked }))} /></div>
            <div className="row"><label>Auto-rotate</label><input type="checkbox" checked={opts.autoRotate} onChange={e => setOpts(o => ({ ...o, autoRotate: e.target.checked }))} /></div>
            <div className="row"><label>Show skeleton</label><input type="checkbox" checked={opts.skeleton} onChange={e => setOpts(o => ({ ...o, skeleton: e.target.checked }))} /></div>
            <div className="row"><label>Background</label>
              <select value={opts.bg} onChange={e => setOpts(o => ({ ...o, bg: e.target.value }))}>
                <option value="dark">Dark</option><option value="slate">Slate</option><option value="light">Light</option>
              </select>
            </div>
          </div>

          <div className="section">
            <h3>Animation</h3>
            {!hasAnim && <div className="hint">This asset has no animation clips.{entry.skins > 0 ? ' (Skinned mesh shown in bind pose.)' : ''}</div>}
            {hasAnim && (
              <>
                <select value={anim.clip || ''} onChange={e => setAnim(a => ({ ...a, clip: e.target.value, playing: Boolean(e.target.value), time: 0, seekMode: 'absolute', seekNonce: a.seekNonce + 1 }))}>
                  <option value="">— none —</option>
                  {clips.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
                <div className="row" style={{ marginTop: 10 }}>
                  <button className="btn primary" onClick={() => setAnim(a => ({ ...a, playing: !a.playing, clip: a.clip || clips[0] }))}>
                    {anim.playing ? '⏸ Pause' : '▶ Play'}
                  </button>
                  <button className="btn" onClick={() => setAnim(a => ({ ...a, clip: clips[(clips.indexOf(a.clip) + 1) % clips.length] || clips[0], playing: true, time: 0, seekMode: 'absolute', seekNonce: a.seekNonce + 1 }))}>Next clip</button>
                </div>
                <div className="row"><label>Loop</label><input type="checkbox" checked={anim.loop} onChange={e => setAnim(a => ({ ...a, loop: e.target.checked }))} /></div>
                <div className="row"><label>Speed {anim.speed.toFixed(2)}×</label></div>
                <input type="range" min="0.05" max="3" step="0.05" value={anim.speed} onChange={e => setAnim(a => ({ ...a, speed: +e.target.value }))} />
                <div className="time-control">
                  <div className="row"><label>GLB time {((info?.time ?? anim.time) || 0).toFixed(3)} / {(info?.duration ?? 0).toFixed(3)}s</label></div>
                  <input type="range" disabled={!anim.clip} min="0" max={Math.max(info?.duration || 0, 0.001)} step="0.001"
                         value={Math.min(info?.time ?? anim.time, info?.duration || anim.time || 0)}
                         onPointerDown={() => setAnim(a => ({ ...a, playing: false }))}
                         onKeyDown={() => setAnim(a => ({ ...a, playing: false }))}
                         onInput={e => onSeek?.(e.currentTarget.valueAsNumber)}
                         onChange={() => {}} />
                  <div className="row"><button className="btn" disabled={!anim.clip} onClick={() => onStep?.(-1 / 30)}>◀ 1/30s</button><button className="btn" disabled={!anim.clip} onClick={() => onStep?.(1 / 30)}>1/30s ▶</button></div>
                  <button className="btn" onClick={onFit}>Fit current pose</button>
                  <p className="hint">Seeking pauses playback. This timeline uses exported clip seconds; the game's authored playback rate is separate.</p>
                </div>
              </>
            )}
          </div>
        </>
      )}
    </div>
  )
}
