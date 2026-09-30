import React, { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Grid, Bounds, useBounds, useGLTF, Html as DreiHtml } from '@react-three/drei'
import * as THREE from 'three'
import { clone as skeletonClone } from 'three/examples/jsm/utils/SkeletonUtils.js'

const BG = { dark: '#0e1116', slate: '#202832', light: '#cfd6de' }

// Error boundary so a bad/missing glb shows a message instead of a white screen.
class GLBoundary extends React.Component {
  constructor(p) { super(p); this.state = { err: null } }
  static getDerivedStateFromError(err) { return { err } }
  componentDidUpdate(prev) { if (prev.resetKey !== this.props.resetKey && this.state.err) this.setState({ err: null }) }
  render() {
    if (this.state.err) return <Html msg={'Failed to load:\n' + String(this.state.err?.message || this.state.err)} cls="err" />
    return this.props.children
  }
}
function Html({ msg, cls }) {
  return <DreiHtml fullscreen><div className={'overlay ' + cls} style={{ inset: 0 }}>{msg}</div></DreiHtml>
}

function Model({ url, wireframe, doubleSide, showSkeleton, anim, onInfo, onTime }) {
  const group = useRef()
  const { scene, animations } = useGLTF(url)
  const cloned = useMemo(() => {
    const copy = skeletonClone(scene)
    copy.traverse(o => {
      if (o.material) o.material = Array.isArray(o.material)
        ? o.material.map(m => m.clone()) : o.material.clone()
    })
    return copy
  }, [scene])
  // Manual mixer rooted at the scene itself (matches the verified headless path). drei's
  // useAnimations roots the mixer at the wrapper <group> and re-binds tracks by sanitized name,
  // which mis-bound the spaced bone names ("L UpperArm" etc.) and scrambled the skin.
  const mixer = useMemo(() => new THREE.AnimationMixer(cloned), [cloned])
  const actionRef = useRef(null)
  const reportAt = useRef(0)
  const bounds = useBounds()
  const pendingFit = useRef(true)
  const names = useMemo(() => animations.map(a => a.name), [animations])

  // CPU-skin bake. three.js GPU skinning blows these glbs up (verified again 2026-06-12: switching
  // to the plain SkinnedMesh path renders blank/exploded even with the corrected remap), while
  // SkinnedMesh.applyBoneTransform (CPU) is provably correct (matches the offline decode to 4 dp).
  // So each frame we bake skinned positions into plain meshes and hide the GPU-skinned originals.
  const baked = useMemo(() => {
    const out = []
    cloned.traverse(o => {
      if (o.isSkinnedMesh) {
        o.visible = false
        const geo = o.geometry.clone()
        geo.deleteAttribute('skinIndex')
        geo.deleteAttribute('skinWeight')
        const mat = (Array.isArray(o.material) ? o.material[0] : o.material).clone()
        out.push({ src: o, geo, base: o.geometry.attributes.position, mesh: new THREE.Mesh(geo, mat), mat })
      }
    })
    return out
  }, [cloned])
  useFrame((_, delta) => {
    mixer.update(delta)
    cloned.updateMatrixWorld(true)
    const v = new THREE.Vector3()
    for (const b of baked) {
      b.src.skeleton.update()
      const dst = b.geo.attributes.position
      for (let i = 0; i < dst.count; i++) {
        v.fromBufferAttribute(b.base, i)
        b.src.applyBoneTransform(i, v)
        dst.setXYZ(i, v.x, v.y, v.z)
      }
      dst.needsUpdate = true
      b.geo.computeVertexNormals()
      b.geo.computeBoundingBox()
      b.geo.computeBoundingSphere()
      // CPU-baked geometry is a sibling of the source mesh. Preserve the source mesh's
      // current local/world transform so non-identity imported mesh nodes do not drift.
      if (group.current) {
        group.current.updateMatrixWorld(true)
        const local = group.current.matrixWorld.clone().invert().multiply(b.src.matrixWorld)
        b.mesh.matrixAutoUpdate = false
        b.mesh.matrix.copy(local)
        b.mesh.matrixWorld.copy(group.current.matrixWorld).multiply(b.mesh.matrix)
      }
    }
    if (pendingFit.current && group.current) {
      const box = new THREE.Box3()
      group.current.traverseVisible(o => {
        if (!o.isMesh || !o.geometry) return
        o.geometry.computeBoundingBox()
        if (o.geometry.boundingBox) box.union(o.geometry.boundingBox.clone().applyMatrix4(o.matrixWorld))
      })
      if (!box.isEmpty()) bounds.refresh(box).clip().fit()
      pendingFit.current = false
    }
    const now = performance.now()
    const action = actionRef.current
    if (action && now >= reportAt.current) {
      reportAt.current = now + 100
      onTime?.({ time: action.time, duration: action.getClip().duration,
        finished: !anim.loop && action.time >= action.getClip().duration })
    }
  })

  // material toggles + report stats once per load
  useEffect(() => {
    let verts = 0, meshes = 0, mats = new Set()
    cloned.traverse(o => {
      if (o.isMesh || o.isSkinnedMesh) {
        meshes++
        if (o.geometry?.attributes?.position) verts += o.geometry.attributes.position.count
        const ms = Array.isArray(o.material) ? o.material : [o.material]
        ms.forEach(m => {
          if (!m) return
          mats.add(m.uuid)
          // TOD assets are old diffuse-textured (non-PBR). glTF defaults metalness=1, which renders
          // BLACK without an env map — force it down so the baseColor/texture lights correctly.
          if ('metalness' in m) m.metalness = 0
          if ('roughness' in m) m.roughness = Math.max(m.roughness ?? 1, 0.6)
          if (m.map) m.map.colorSpace = THREE.SRGBColorSpace
          m.wireframe = wireframe
          m.side = doubleSide ? THREE.DoubleSide : THREE.FrontSide
          m.needsUpdate = true
        })
      }
    })
    // baked twins use their own material clones — mutate them the same way
    baked.forEach(b => {
      const m = b.mat
      if ('metalness' in m) m.metalness = 0
      if ('roughness' in m) m.roughness = Math.max(m.roughness ?? 1, 0.6)
      if (m.map) m.map.colorSpace = THREE.SRGBColorSpace
      m.wireframe = wireframe
      m.side = doubleSide ? THREE.DoubleSide : THREE.FrontSide
      m.needsUpdate = true
    })
    onInfo?.({ clips: names, verts, meshes, materials: mats.size, hasSkeleton: hasBones(cloned) })
  }, [cloned, baked, wireframe, doubleSide, names])

  // animation playback
  useEffect(() => {
    mixer.stopAllAction()
    actionRef.current = null
    if (!anim.clip) {
      onTime?.({ time: 0, duration: 0, finished: false })
      return
    }
    const clip = animations.find(c => c.name === anim.clip)
    if (!clip) return
    const a = mixer.clipAction(clip)
    a.reset()
    a.setLoop(anim.loop ? THREE.LoopRepeat : THREE.LoopOnce, Infinity)
    a.clampWhenFinished = !anim.loop
    a.timeScale = 1
    a.play()
    a.paused = !anim.playing
    actionRef.current = a
  }, [mixer, animations, anim.clip])
  useEffect(() => {
    if (actionRef.current) {
      actionRef.current.setLoop(anim.loop ? THREE.LoopRepeat : THREE.LoopOnce, Infinity)
      actionRef.current.clampWhenFinished = true
    }
  }, [anim.loop, anim.clip])
  useEffect(() => {
    const action = actionRef.current
    if (!action) return
    if (anim.playing && !anim.loop && action.time >= action.getClip().duration) action.reset().play()
    action.paused = !anim.playing
  }, [anim.playing])
  useEffect(() => { mixer.timeScale = anim.speed }, [mixer, anim.speed])
  useEffect(() => {
    const action = actionRef.current
    if (!action) return
    const target = anim.seekMode === 'relative' ? action.time + anim.stepDelta : (anim.time || 0)
    action.reset().play()
    action.paused = !anim.playing
    action.time = THREE.MathUtils.clamp(target, 0, action.getClip().duration)
    mixer.update(0)
    onTime?.({ time: action.time, duration: action.getClip().duration })
  }, [anim.seekNonce])
  useEffect(() => { pendingFit.current = true }, [anim.fitNonce, anim.clip, cloned])
  useEffect(() => () => {
    mixer.stopAllAction(); mixer.uncacheRoot(cloned)
    baked.forEach(b => { b.geo.dispose(); b.mat.dispose() })
    cloned.traverse(o => {
      if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => m.dispose())
    })
  }, [mixer, cloned, baked])

  return (
    <group ref={group}>
      <primitive object={cloned} />
      {baked.map((b, i) => <primitive key={i} object={b.mesh} />)}
      {showSkeleton && <BoneViz root={cloned} />}
    </group>
  )
}

function hasBones(root) {
  let found = false
  root.traverse(o => { if (o.isBone) found = true })
  return found
}

// Visualizes any animated node hierarchy (works for glTF skeleton-only exports where nodes
// aren't typed as Bone, which SkeletonHelper ignores). Spheres are parented to each node so they
// inherit the clip's animation for free; the connecting lines are rebuilt each frame from world
// positions. Also gives <Bounds> real geometry to frame when the asset has no skinned mesh.
function BoneViz({ root }) {
  const linesRef = useRef()
  const { nodes, pairs, radius, geom } = useMemo(() => {
    const nodes = []
    root.traverse(o => { if (o !== root && !o.isMesh && !o.isSkinnedMesh) nodes.push(o) })
    const set = new Set(nodes)
    const pairs = []
    for (const n of nodes) if (set.has(n.parent)) pairs.push([n.parent, n])
    // size markers from the spread of node positions
    const box = new THREE.Box3()
    const v = new THREE.Vector3()
    nodes.forEach(n => box.expandByPoint(n.getWorldPosition(v)))
    const diag = box.isEmpty() ? 1 : box.getSize(v).length()
    const radius = Math.max(diag * 0.012, 0.002)
    const geom = new THREE.BufferGeometry()
    geom.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pairs.length * 6), 3))
    return { nodes, pairs, radius, geom }
  }, [root])

  const bounds = useBounds()
  // attach a sphere marker under each node (inherits its animated transform), then refit camera
  useEffect(() => {
    const geo = new THREE.SphereGeometry(radius, 8, 8)
    const mat = new THREE.MeshBasicMaterial({ color: 0xe8a13a })
    const added = nodes.map(n => { const m = new THREE.Mesh(geo, mat); n.add(m); return [n, m] })
    root.updateWorldMatrix(true, true)
    const id = requestAnimationFrame(() => bounds.refresh().clip().fit())
    return () => { cancelAnimationFrame(id); added.forEach(([n, m]) => n.remove(m)) }
  }, [nodes, radius])

  useFrame(() => {
    if (!pairs.length) return
    const pos = geom.attributes.position.array
    const a = new THREE.Vector3(), b = new THREE.Vector3()
    pairs.forEach(([p, c], i) => {
      p.getWorldPosition(a); c.getWorldPosition(b)
      pos.set([a.x, a.y, a.z, b.x, b.y, b.z], i * 6)
    })
    geom.attributes.position.needsUpdate = true
  })

  return (
    <lineSegments ref={linesRef} geometry={geom}>
      <lineBasicMaterial color={0x4b9fff} />
    </lineSegments>
  )
}

export default function Viewer({ url, opts, anim, onInfo, onTime }) {
  return (
    <Canvas camera={{ position: [3, 2, 4], fov: 45, near: 0.01, far: 5000 }} dpr={[1, 2]}
            gl={{ preserveDrawingBuffer: true }}>
      <color attach="background" args={[BG[opts.bg] || BG.dark]} />
      <hemisphereLight intensity={0.9} groundColor={'#202020'} />
      <directionalLight position={[5, 8, 5]} intensity={1.6} castShadow />
      <directionalLight position={[-6, 3, -4]} intensity={0.5} />
      <ambientLight intensity={0.25} />
      {opts.grid && (
        <Grid infiniteGrid cellSize={0.5} sectionSize={2.5} sectionColor={'#3a4655'} cellColor={'#262d36'}
              fadeDistance={40} fadeStrength={1.5} position={[0, -0.001, 0]} />
      )}
      <Suspense fallback={null}>
        <GLBoundary resetKey={url}>
          {url && (
              <Bounds key={url} margin={1.25}>
                <Model url={url} wireframe={opts.wireframe} doubleSide={opts.doubleSide}
                       showSkeleton={opts.skeleton} anim={anim} onInfo={onInfo}
                       onTime={onTime} />
            </Bounds>
          )}
        </GLBoundary>
      </Suspense>
      <OrbitControls makeDefault enableDamping autoRotate={opts.autoRotate} autoRotateSpeed={1.2} />
    </Canvas>
  )
}
