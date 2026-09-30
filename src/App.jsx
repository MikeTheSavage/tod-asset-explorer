import React, { useEffect, useMemo, useState } from 'react'
import Sidebar from './Sidebar.jsx'
import Inspector from './Inspector.jsx'
import Viewer from './Viewer.jsx'
import EmptyState from './EmptyState.jsx'

export default function App() {
  const [all, setAll] = useState([])
  const [meta, setMeta] = useState(null)
  const [tab, setTab] = useState('geometry')
  const [q, setQ] = useState('')
  const [cat, setCat] = useState('All')
  const [selId, setSelId] = useState(null)
  const [info, setInfo] = useState(null)
  const [opts, setOpts] = useState({ wireframe: false, doubleSide: true, grid: true, autoRotate: false, skeleton: false, bg: 'dark' })
  const [anim, setAnim] = useState({ clip: null, playing: false, loop: true, speed: 1, time: 0, seekNonce: 0, fitNonce: 0 })

  const [loadError, setLoadError] = useState(null)
  useEffect(() => {
    fetch('manifest.json', { cache: 'no-store' })
      .then(r => { if (!r.ok) throw new Error(`manifest.json: HTTP ${r.status}`); return r.json() })
      .then(m => { setAll(m.entries || []); setMeta(m) })
      .catch(e => setLoadError(String(e.message || e)))
  }, [])

  // entries for the current tab + search
  const tabEntries = useMemo(() => {
    let e = all
    if (tab === 'animation') e = e.filter(x => x.anims > 0 || x.skins > 0)
    const s = q.trim().toLowerCase()
    if (s) e = e.filter(x => x.label.toLowerCase().includes(s) || x.file.toLowerCase().includes(s))
    return e
  }, [all, tab, q])

  const sel = useMemo(() => all.find(e => e.id === selId) || null, [all, selId])

  // on tab switch, reset filters and auto-pick a sensible default
  useEffect(() => {
    setCat('All'); setInfo(null)
    if (tab === 'animation') {
      // default to the lightest animated asset so the tab opens instantly; the humanoid
      // characters (several hundred clips, ~8 MB each) load when the user picks one.
      const pick = [...all].filter(x => x.anims > 0).sort((a, b) => a.kb - b.kb)[0]
        || all.find(x => x.skins > 0)
      if (pick) {
        setSelId(pick.id)
        // Do NOT force the skeleton overlay on: BoneViz refits the camera to include every bone
        // marker, and an unused/mislocated pivot (emitter/GamePivot with no anim track) sits far out,
        // which zooms the character down to a dot. The mesh animates correctly without it; the user
        // can still toggle "Show skeleton" to inspect the rig.
        setOpts(o => ({ ...o, skeleton: false, autoRotate: false }))
        setAnim(a => ({ ...a, clip: pick.clips?.[0] || null, playing: true, time: 0, seekMode: 'absolute', seekNonce: a.seekNonce + 1 }))
      }
    }
  }, [tab, all])

  // reset per-selection state
  useEffect(() => {
    setInfo(null)
    setAnim(a => ({ ...a, clip: tab === 'animation' ? (sel?.clips?.[0] || null) : null, playing: tab === 'animation', time: 0, seekMode: 'absolute', seekNonce: a.seekNonce + 1 }))
  }, [selId])

  return (
    <div className="app">
      <div className="topbar">
        <h1>Total Overdose <span>·</span> Asset Explorer</h1>
        <div className="tabs">
          <button className={'tab' + (tab === 'geometry' ? ' active' : '')} onClick={() => setTab('geometry')}>Geometry</button>
          <button className={'tab' + (tab === 'animation' ? ' active' : '')} onClick={() => setTab('animation')}>Animation</button>
        </div>
        <input className="search" placeholder="Search models…" value={q} onChange={e => setQ(e.target.value)} />
        <div className="count">{tabEntries.length} / {all.length}</div>
      </div>

      <div className="body">
        <Sidebar entries={tabEntries} cat={cat} setCat={setCat} selId={selId} setSelId={setSelId} />
        <div className="stage">
          {sel ? (
            <Viewer url={sel.url} opts={opts} anim={anim} onInfo={setInfo}
                    onTime={sample => {
                      setInfo(i => ({ ...(i || {}), ...sample }))
                      if (sample.finished) setAnim(a => a.playing ? ({ ...a, playing: false }) : a)
                    }} />
          ) : loadError || (meta && all.length === 0) ? (
            <EmptyState meta={meta} error={loadError} />
          ) : (
            <div className="overlay empty" style={{ inset: 0 }}>
              {meta ? 'Pick a model to preview' : 'Loading manifest…'}
            </div>
          )}
          {sel && <div className="overlay statline">{sel.file}{info?.verts ? ` · ${info.verts.toLocaleString()} verts` : ''}</div>}
        </div>
          <Inspector entry={sel} info={info} opts={opts} setOpts={setOpts} anim={anim} setAnim={setAnim}
                     onSeek={time => setAnim(a => ({ ...a, time, seekMode: 'absolute', playing: false, seekNonce: a.seekNonce + 1 }))}
                     onStep={delta => setAnim(a => ({ ...a, stepDelta: delta, seekMode: 'relative', playing: false, seekNonce: a.seekNonce + 1 }))}
                     onFit={() => setAnim(a => ({ ...a, fitNonce: a.fitNonce + 1 }))} />
      </div>
    </div>
  )
}
