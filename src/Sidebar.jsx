import React, { useMemo } from 'react'

export default function Sidebar({ entries, cat, setCat, selId, setSelId }) {
  const cats = useMemo(() => {
    const c = {}
    for (const e of entries) c[e.map] = (c[e.map] || 0) + 1
    const order = Object.keys(c).sort((a, b) => {
      const am = a.match(/Map(\d+)/), bm = b.match(/Map(\d+)/)
      if (am && bm) return +am[1] - +bm[1]
      if (am) return 1; if (bm) return -1
      return a.localeCompare(b)
    })
    return ['All', ...order]
  }, [entries])

  const shown = cat === 'All' ? entries : entries.filter(e => e.map === cat)

  return (
    <div className="sidebar">
      <div className="cats">
        {cats.map(c => (
          <div key={c} className={'chip' + (c === cat ? ' active' : '')} onClick={() => setCat(c)}>
            {c}{c !== 'All' ? '' : ` (${entries.length})`}
          </div>
        ))}
      </div>
      <div className="list">
        {shown.map(e => (
          <div key={e.id} className={'item' + (e.id === selId ? ' sel' : '')} onClick={() => setSelId(e.id)} title={e.file}>
            <span className="nm">{e.label}</span>
            {e.anims > 0 && <span className="badge anim">{e.anims}🎞</span>}
            {e.skins > 0 && <span className="badge skin">rig</span>}
            {e.source === 'textured' && <span className="badge">tex</span>}
          </div>
        ))}
        {shown.length === 0 && <div className="hint" style={{ padding: 12 }}>No models match.</div>}
      </div>
    </div>
  )
}
