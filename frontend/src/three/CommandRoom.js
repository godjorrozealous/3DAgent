import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

const STATUS_COLORS = {
  idle: 0x0e7490,
  running: 0xfbbf24,
  completed: 0x34d399,
  error: 0xf87171,
}

// 席位布局：作战指挥室 —— 后排大屏，司令员居中高台，诊断员分列左右两排，审核员前侧独立席位
const STATIONS = [
  { id: 'commander', label: '司令员', pos: [0, 0, -8], rotY: 0, kind: 'officer' },
  { id: 'lightning', label: '雷电诊断', pos: [-11, 0, -4], rotY: Math.PI / 2, kind: 'researcher' },
  { id: 'wind', label: '风偏诊断', pos: [-11, 0, 2.5], rotY: Math.PI / 2, kind: 'researcher' },
  { id: 'icing', label: '覆冰诊断', pos: [11, 0, -4], rotY: -Math.PI / 2, kind: 'researcher' },
  { id: 'bird', label: '鸟害诊断', pos: [11, 0, 2.5], rotY: -Math.PI / 2, kind: 'researcher' },
  { id: 'audit', label: '报告审核', pos: [6.5, 0, 7.5], rotY: Math.PI, kind: 'writer' },
]

const CMD_POS = new THREE.Vector3(0, 0, -8)

/* ---------------- 基础构件 ---------------- */

function makeLabel(text) {
  const canvas = document.createElement('canvas')
  canvas.width = 512
  canvas.height = 128
  const ctx = canvas.getContext('2d')
  ctx.font = 'bold 56px "PingFang SC", sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.shadowColor = '#22d3ee'
  ctx.shadowBlur = 18
  ctx.fillStyle = '#a5f3fc'
  ctx.fillText(text, 256, 64)
  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true, depthWrite: false })
  )
  sprite.scale.set(3.4, 0.85, 1)
  return sprite
}

// 两点之间的圆柱肢体
function limb(a, b, r, mat) {
  const dir = new THREE.Vector3().subVectors(b, a)
  const len = dir.length()
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, 10), mat)
  mesh.position.copy(a).add(b).multiplyScalar(0.5)
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize())
  return mesh
}

const MAT = {
  desk: new THREE.MeshStandardMaterial({ color: 0xe8edf2, metalness: 0.3, roughness: 0.5 }),
  chair: new THREE.MeshStandardMaterial({ color: 0xcfd8e0, roughness: 0.6 }),
  skin: new THREE.MeshStandardMaterial({ color: 0xf1c27d, roughness: 0.7 }),
  dark: new THREE.MeshStandardMaterial({ color: 0x5a6672, roughness: 0.7 }),
  gold: new THREE.MeshStandardMaterial({ color: 0xd4af37, metalness: 0.8, roughness: 0.3 }),
  paper: new THREE.MeshStandardMaterial({ color: 0xe8e8e8, roughness: 0.9 }),
}

function makeDesk(accentMat, width = 3.2) {
  const g = new THREE.Group()
  const top = new THREE.Mesh(new THREE.BoxGeometry(width, 0.12, 1.5), MAT.desk)
  top.position.y = 1.06
  g.add(top)
  for (const x of [-width / 2 + 0.1, width / 2 - 0.1]) {
    const panel = new THREE.Mesh(new THREE.BoxGeometry(0.1, 1.06, 1.4), MAT.desk)
    panel.position.set(x, 0.53, 0)
    g.add(panel)
  }
  // 桌面边缘状态灯带（随智能体状态变色）
  const strip = new THREE.Mesh(new THREE.BoxGeometry(width, 0.05, 0.05), accentMat)
  strip.position.set(0, 0.98, 0.76)
  g.add(strip)
  return g
}

function makeChair() {
  const g = new THREE.Group()
  const seat = new THREE.Mesh(new THREE.BoxGeometry(0.95, 0.12, 0.9), MAT.chair)
  seat.position.y = 0.58
  const back = new THREE.Mesh(new THREE.BoxGeometry(0.95, 1.0, 0.12), MAT.chair)
  back.position.set(0, 1.1, -0.45)
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.55, 10), MAT.dark)
  pole.position.y = 0.3
  const base = new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.42, 0.05, 16), MAT.dark)
  base.position.y = 0.03
  g.add(seat, back, pole, base)
  return g
}

function makeMonitor(accentMat) {
  const g = new THREE.Group()
  const stand = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.35, 0.12), MAT.dark)
  stand.position.y = 1.3
  const frame = new THREE.Mesh(new THREE.BoxGeometry(1.15, 0.72, 0.06), MAT.dark)
  frame.position.set(0, 1.72, 0)
  frame.rotation.x = -0.1
  // 屏幕朝向席位（-z），颜色随状态变化
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(1.05, 0.62), accentMat)
  screen.position.set(0, 1.72, -0.035)
  screen.rotation.x = -0.1
  screen.rotation.y = Math.PI
  g.add(stand, frame, screen)
  return g
}

/* ---------------- 人形角色 ---------------- */

function makeHead({ glasses = false, cap = false } = {}) {
  const head = new THREE.Group()
  const skull = new THREE.Mesh(new THREE.SphereGeometry(0.3, 20, 16), MAT.skin)
  head.add(skull)

  if (cap) {
    // 军帽：帽顶 + 帽檐 + 金色帽带
    const top = new THREE.Mesh(new THREE.CylinderGeometry(0.31, 0.33, 0.18, 20), MAT.dark)
    top.position.y = 0.28
    const brim = new THREE.Mesh(new THREE.CylinderGeometry(0.44, 0.44, 0.035, 20), MAT.dark)
    brim.position.set(0, 0.21, 0.05)
    const band = new THREE.Mesh(new THREE.CylinderGeometry(0.335, 0.335, 0.05, 20), MAT.gold)
    band.position.y = 0.22
    head.add(top, brim, band)
  } else {
    const hair = new THREE.Mesh(new THREE.SphereGeometry(0.31, 20, 16), MAT.dark)
    hair.scale.set(1, 0.85, 1)
    hair.position.set(0, 0.06, -0.05)
    head.add(hair)
  }

  if (glasses) {
    // 眼镜：两个圆环 + 鼻梁
    const gmat = new THREE.MeshStandardMaterial({ color: 0x111827, metalness: 0.7, roughness: 0.3 })
    for (const x of [-0.11, 0.11]) {
      const lens = new THREE.Mesh(new THREE.TorusGeometry(0.085, 0.014, 8, 20), gmat)
      lens.position.set(x, 0.02, 0.27)
      head.add(lens)
    }
    const bridge = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.015, 0.015), gmat)
    bridge.position.set(0, 0.02, 0.285)
    head.add(bridge)
  }
  return head
}

// 军官（司令员）：站姿，军装 + 军帽 + 金色肩章
function makeOfficer() {
  const g = new THREE.Group()
  const uniform = new THREE.MeshStandardMaterial({ color: 0x3f4a3c, roughness: 0.6 })
  g.add(limb(new THREE.Vector3(-0.16, 0, 0), new THREE.Vector3(-0.16, 0.95, 0), 0.13, MAT.dark))
  g.add(limb(new THREE.Vector3(0.16, 0, 0), new THREE.Vector3(0.16, 0.95, 0), 0.13, MAT.dark))
  const torso = new THREE.Mesh(new THREE.CylinderGeometry(0.36, 0.43, 0.95, 16), uniform)
  torso.position.y = 1.42
  g.add(torso)
  g.add(limb(new THREE.Vector3(-0.42, 1.82, 0), new THREE.Vector3(-0.52, 1.1, 0.08), 0.08, uniform))
  g.add(limb(new THREE.Vector3(0.42, 1.82, 0), new THREE.Vector3(0.52, 1.1, 0.08), 0.08, uniform))
  for (const x of [-0.34, 0.34]) {
    const board = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.04, 0.3), MAT.gold)
    board.position.set(x, 1.9, 0)
    g.add(board)
  }
  const head = makeHead({ cap: true })
  head.position.y = 2.18
  g.add(head)
  return g
}

// 研究员（诊断员）：坐姿，白大褂 + 眼镜，手伸向桌面键盘
function makeResearcher({ writing = false } = {}) {
  const g = new THREE.Group()
  const coat = new THREE.MeshStandardMaterial({ color: writing ? 0x9db4c8 : 0xdfe5ec, roughness: 0.65 })

  // 坐姿腿部：大腿水平 + 小腿垂直
  for (const x of [-0.15, 0.15]) {
    const thigh = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.16, 0.55), MAT.dark)
    thigh.position.set(x, 0.62, 0.18)
    const shin = new THREE.Mesh(new THREE.BoxGeometry(0.15, 0.55, 0.15), MAT.dark)
    shin.position.set(x, 0.3, 0.42)
    g.add(thigh, shin)
  }

  const torso = new THREE.Mesh(new THREE.CylinderGeometry(0.34, 0.4, 0.85, 16), coat)
  torso.position.y = 1.13
  if (writing) torso.rotation.x = 0.18 // 伏案前倾
  g.add(torso)

  if (writing) {
    // 右手执笔伸向纸上，左手搭桌沿
    g.add(limb(new THREE.Vector3(0.4, 1.42, 0.05), new THREE.Vector3(0.3, 1.14, 0.72), 0.07, coat))
    g.add(limb(new THREE.Vector3(-0.4, 1.42, 0.05), new THREE.Vector3(-0.35, 1.12, 0.45), 0.07, coat))
  } else {
    g.add(limb(new THREE.Vector3(-0.4, 1.42, 0.05), new THREE.Vector3(-0.28, 1.14, 0.6), 0.07, coat))
    g.add(limb(new THREE.Vector3(0.4, 1.42, 0.05), new THREE.Vector3(0.28, 1.14, 0.6), 0.07, coat))
  }

  const head = makeHead({ glasses: !writing })
  head.position.y = 1.87
  if (writing) head.position.z = 0.12
  g.add(head)
  return g
}

/* ---------------- 策略浮牌（司令员席位旁） ---------------- */

function drawStrategyBoard(canvas, text) {
  const ctx = canvas.getContext('2d')
  const { width: W, height: H } = canvas
  // 半透明全息底
  ctx.fillStyle = 'rgba(4,16,29,0.92)'
  ctx.fillRect(0, 0, W, H)
  // 边框 + 四角瞄准框
  ctx.strokeStyle = 'rgba(34,211,238,0.5)'
  ctx.lineWidth = 3
  ctx.strokeRect(10, 10, W - 20, H - 20)
  ctx.strokeStyle = '#22d3ee'
  ctx.lineWidth = 5
  for (const [x, y, dx, dy] of [[10, 10, 1, 1], [W - 10, 10, -1, 1], [10, H - 10, 1, -1], [W - 10, H - 10, -1, -1]]) {
    ctx.beginPath(); ctx.moveTo(x, y + 36 * dy); ctx.lineTo(x, y); ctx.lineTo(x + 36 * dx, y); ctx.stroke()
  }
  // 多行文本
  ctx.font = 'bold 40px "PingFang SC", sans-serif'
  ctx.textAlign = 'left'
  ctx.textBaseline = 'top'
  ctx.shadowColor = '#22d3ee'
  ctx.shadowBlur = 10
  String(text).split('\n').forEach((line, i) => {
    ctx.fillStyle = i === 0 ? '#67e8f9' : '#a5f3fc'
    ctx.fillText(line, 40, 34 + i * 76)
  })
}

/* ---------------- 大屏贴图 ---------------- */

function makeScreenTexture() {
  const c = document.createElement('canvas')
  c.width = 1024
  c.height = 512
  const ctx = c.getContext('2d')
  ctx.fillStyle = '#04101d'
  ctx.fillRect(0, 0, 1024, 512)

  ctx.strokeStyle = 'rgba(34,211,238,0.12)'
  for (let x = 0; x <= 1024; x += 40) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, 512); ctx.stroke() }
  for (let y = 0; y <= 512; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(1024, y); ctx.stroke() }

  ctx.font = 'bold 42px "PingFang SC", sans-serif'
  ctx.textAlign = 'center'
  ctx.shadowColor = '#22d3ee'
  ctx.shadowBlur = 16
  ctx.fillStyle = '#67e8f9'
  ctx.fillText('输电线路智能诊断 · 综合态势', 512, 70)

  // 波形
  ctx.shadowBlur = 8
  ctx.lineWidth = 3
  for (const [color, amp, yBase, phase] of [['#22d3ee', 40, 220, 0], ['#fbbf24', 25, 260, 2]]) {
    ctx.strokeStyle = color
    ctx.beginPath()
    for (let x = 0; x <= 1024; x += 8) {
      const y = yBase + Math.sin(x / 60 + phase) * amp + Math.sin(x / 17) * 8
      x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
    }
    ctx.stroke()
  }

  // 柱状图
  const bars = [0.4, 0.7, 0.5, 0.9, 0.65, 0.35, 0.8, 0.55]
  ctx.fillStyle = 'rgba(52,211,153,0.7)'
  bars.forEach((v, i) => ctx.fillRect(120 + i * 100, 460 - v * 120, 50, v * 120))

  // 四角瞄准框
  ctx.shadowBlur = 0
  ctx.strokeStyle = '#22d3ee'
  ctx.lineWidth = 4
  for (const [x, y, dx, dy] of [[16, 16, 1, 1], [1008, 16, -1, 1], [16, 496, 1, -1], [1008, 496, -1, -1]]) {
    ctx.beginPath(); ctx.moveTo(x, y + 40 * dy); ctx.lineTo(x, y); ctx.lineTo(x + 40 * dx, y); ctx.stroke()
  }

  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

/* ---------------- 幕墙外天际线贴图（天蓝→远山灰渐变 + 楼群剪影） ---------------- */

function makeSkylineTexture() {
  const c = document.createElement('canvas')
  c.width = 512
  c.height = 256
  const ctx = c.getContext('2d')
  const grad = ctx.createLinearGradient(0, 0, 0, 256)
  grad.addColorStop(0, '#c4dcef')
  grad.addColorStop(0.55, '#aec6da')
  grad.addColorStop(1, '#93a9bc')
  ctx.fillStyle = grad
  ctx.fillRect(0, 0, 512, 256)
  // 远山剪影
  ctx.fillStyle = 'rgba(126,146,164,0.5)'
  ctx.beginPath()
  ctx.moveTo(0, 190)
  for (const [x, y] of [[60, 150], [130, 185], [210, 145], [300, 190], [390, 155], [460, 185], [512, 165]]) {
    ctx.lineTo(x, y)
  }
  ctx.lineTo(512, 256); ctx.lineTo(0, 256); ctx.closePath(); ctx.fill()
  // 远处楼群剪影
  ctx.fillStyle = 'rgba(104,124,142,0.65)'
  const heights = [70, 110, 88, 130, 96, 60, 118, 82, 140, 100, 76, 124]
  heights.forEach((h, i) => ctx.fillRect(8 + i * 42, 256 - h, 30, h))
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

/* ---------------- 指挥室主类 ---------------- */

export class CommandRoom {
  constructor(container, onAgentDblClick) {
    this.onAgentDblClick = onAgentDblClick
    this.nodes = {}
    this.links = {}
    this.clickables = []
    this.focusTarget = null
    this.clock = new THREE.Clock()

    this.renderer = new THREE.WebGLRenderer({ antialias: true })
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
    this.renderer.setSize(container.clientWidth, container.clientHeight)
    // 明亮写实光照强度较高，用 ACES 色调映射压高光、保留层次
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping
    this.renderer.toneMappingExposure = 0.55
    container.appendChild(this.renderer.domElement)

    this.scene = new THREE.Scene()
    this.scene.background = new THREE.Color(0xdfe8f0)
    this.scene.fog = new THREE.FogExp2(0xdfe8f0, 0.004)
    this.camera = new THREE.PerspectiveCamera(
      55, container.clientWidth / container.clientHeight, 0.1, 500
    )
    this.camera.position.set(0, 13.75, 30)

    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.06
    this.controls.maxDistance = 70
    this.controls.minDistance = 2.5
    this.controls.maxPolarAngle = Math.PI / 2.05
    this.controls.target.set(0, 2, -3)

    this.raycaster = new THREE.Raycaster()
    this.pointer = new THREE.Vector2()

    this._buildLights()
    this._buildRoom()
    this._buildStrategyBoard()
    this._buildStations()
    this._buildLinks()
    this._bindEvents(container)
    this._animate()
  }

  _buildLights() {
    this.scene.add(new THREE.AmbientLight(0xffffff, 3.2))
    const hemi = new THREE.HemisphereLight(0xffffff, 0xb0c4d4, 1.6)
    this.scene.add(hemi)
    // 顶部平行光：模拟天窗日光
    const sun = new THREE.DirectionalLight(0xfff5e6, 2.2)
    sun.position.set(0, 18, 4)
    this.scene.add(sun)
    const screenGlow = new THREE.PointLight(0x2a6f8f, 30, 40)
    screenGlow.position.set(0, 7, -14)
    this.scene.add(screenGlow)
  }

  _buildRoom() {
    // 浅灰白地板 + 浅网格
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(48, 42),
      new THREE.MeshStandardMaterial({ color: 0xdde4ea, roughness: 0.35, metalness: 0.1 })
    )
    floor.rotation.x = -Math.PI / 2
    floor.position.z = -3
    this.scene.add(floor)

    const grid = new THREE.GridHelper(48, 48, 0x9fb3c8, 0xc3d2de)
    grid.material.transparent = true
    grid.material.opacity = 0.25
    grid.position.set(0, 0.02, -3)
    this.scene.add(grid)

    // 白色环形外壳：后墙 + 侧墙
    const wallMat = new THREE.MeshStandardMaterial({ color: 0xeef2f5, roughness: 0.9 })
    const backWall = new THREE.Mesh(new THREE.PlaneGeometry(48, 16), wallMat)
    backWall.position.set(0, 8, -18)
    this.scene.add(backWall)
    for (const x of [-24, 24]) {
      const wall = new THREE.Mesh(new THREE.PlaneGeometry(42, 16), wallMat)
      wall.rotation.y = x < 0 ? Math.PI / 2 : -Math.PI / 2
      wall.position.set(x, 8, -3)
      this.scene.add(wall)
    }

    // 玻璃幕墙 + 幕墙外天际线（由外到内：白外壳 → 天际线 → 玻璃）
    const skylineMat = new THREE.MeshBasicMaterial({ color: 0x9db8cc, map: makeSkylineTexture() })
    const backSkyline = new THREE.Mesh(new THREE.PlaneGeometry(80, 14), skylineMat)
    backSkyline.position.set(0, 7, -30)
    this.scene.add(backSkyline)
    const glassMat = new THREE.MeshPhysicalMaterial({
      color: 0xbfd9e8, transparent: true, opacity: 0.25, roughness: 0.1,
    })
    for (const x of [-22, 22]) {
      const glass = new THREE.Mesh(new THREE.PlaneGeometry(42, 10), glassMat)
      glass.rotation.y = x < 0 ? Math.PI / 2 : -Math.PI / 2
      glass.position.set(x, 6, -3)
      this.scene.add(glass)
      const skyline = new THREE.Mesh(new THREE.PlaneGeometry(44, 14), skylineMat)
      skyline.rotation.y = x < 0 ? Math.PI / 2 : -Math.PI / 2
      skyline.position.set(x < 0 ? -23 : 23, 7, -3)
      this.scene.add(skyline)
    }

    // 格栅天窗：发光顶板 + 两组格栅梁
    const skylight = new THREE.Mesh(
      new THREE.PlaneGeometry(48, 42),
      new THREE.MeshBasicMaterial({ color: 0xf4f8fb })
    )
    skylight.rotation.x = Math.PI / 2 // 朝下发光
    skylight.position.set(0, 14, -3)
    this.scene.add(skylight)
    const beamMat = new THREE.MeshStandardMaterial({ color: 0xc9d4dc, roughness: 0.8 })
    for (let i = 0; i < 21; i++) {
      const beam = new THREE.Mesh(new THREE.BoxGeometry(48, 0.12, 0.3), beamMat)
      beam.position.set(0, 13.9, -23 + i * 2)
      this.scene.add(beam)
    }
    for (let i = 0; i < 25; i++) {
      const beam = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.12, 42), beamMat)
      beam.position.set(-24 + i * 2, 13.9, -3)
      this.scene.add(beam)
    }

    // 弧形视频墙（替代原平面大屏），圆柱中心在 (0,6.8,3)，弧面朝向席位区
    const thetaStart = Math.PI * 0.85
    const thetaLength = Math.PI * 0.3
    const screenTex = makeScreenTexture()
    screenTex.wrapS = THREE.RepeatWrapping
    screenTex.repeat.x = -1 // BackSide 内侧观看需水平翻转，避免贴图镜像
    const screen = new THREE.Mesh(
      new THREE.CylinderGeometry(20, 20, 7.5, 48, 1, true, thetaStart, thetaLength),
      new THREE.MeshBasicMaterial({ map: screenTex, side: THREE.BackSide })
    )
    screen.position.set(0, 6.8, 3)
    this.scene.add(screen)
    // 同弧度深色外壳（半径 20.2）
    const frame = new THREE.Mesh(
      new THREE.CylinderGeometry(20.2, 20.2, 8.1, 48, 1, true, thetaStart, thetaLength),
      new THREE.MeshStandardMaterial({
        color: 0x3a4652, metalness: 0.6, roughness: 0.4, side: THREE.DoubleSide,
      })
    )
    frame.position.set(0, 6.8, 3)
    this.scene.add(frame)

    // 大屏下沿弧形灯带
    const glow = new THREE.Mesh(
      new THREE.CylinderGeometry(19.9, 19.9, 0.08, 48, 1, true, thetaStart, thetaLength),
      new THREE.MeshBasicMaterial({ color: 0x22d3ee, side: THREE.DoubleSide })
    )
    glow.position.set(0, 2.7, 3)
    this.scene.add(glow)

    // 漂浮尘埃粒子（指挥室氛围）
    const count = 350
    const pos = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      pos[i * 3] = (Math.random() - 0.5) * 44
      pos[i * 3 + 1] = Math.random() * 12 + 0.5
      pos[i * 3 + 2] = (Math.random() - 0.5) * 38 - 3
    }
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    this.dust = new THREE.Points(
      geo,
      new THREE.PointsMaterial({ color: 0x8fa8bd, size: 0.08, transparent: true, opacity: 0.35 })
    )
    this.scene.add(this.dust)
  }

  // 司令员席位旁的策略全息浮牌
  _buildStrategyBoard() {
    const canvas = document.createElement('canvas')
    canvas.width = 640
    canvas.height = 320
    this.strategyCanvas = canvas
    this.strategyTex = new THREE.CanvasTexture(canvas)
    this.strategyTex.colorSpace = THREE.SRGBColorSpace
    const board = new THREE.Mesh(
      new THREE.PlaneGeometry(3.2, 1.6),
      new THREE.MeshBasicMaterial({ map: this.strategyTex, transparent: true })
    )
    board.position.set(3.4, 2.6, -8)
    this.scene.add(board)
    // 浮牌下沿灯带
    const glow = new THREE.Mesh(
      new THREE.BoxGeometry(3.2, 0.03, 0.03),
      new THREE.MeshBasicMaterial({ color: 0x22d3ee })
    )
    glow.position.set(3.4, 1.78, -8)
    this.scene.add(glow)
    this.updateStrategy('策略：默认')
  }

  updateStrategy(text) {
    drawStrategyBoard(this.strategyCanvas, text)
    this.strategyTex.needsUpdate = true
  }

  _buildStations() {
    for (const def of STATIONS) {
      const station = new THREE.Group()
      station.position.set(...def.pos)
      station.rotation.y = def.rotY

      const accentMat = new THREE.MeshStandardMaterial({
        color: STATUS_COLORS.idle,
        emissive: STATUS_COLORS.idle,
        emissiveIntensity: 0.7,
        roughness: 0.3,
      })

      let figure
      if (def.kind === 'officer') {
        // 高台 + 指挥桌 + 军官
        const dais = new THREE.Mesh(
          new THREE.CylinderGeometry(3.2, 3.5, 0.3, 32),
          new THREE.MeshStandardMaterial({ color: 0x111c2e, metalness: 0.5, roughness: 0.5 })
        )
        dais.position.y = 0.15
        station.add(dais)
        const rim = new THREE.Mesh(new THREE.TorusGeometry(3.35, 0.05, 10, 60), accentMat)
        rim.rotation.x = Math.PI / 2
        rim.position.y = 0.3
        station.add(rim)

        const desk = makeDesk(accentMat, 4.6)
        desk.position.set(0, 0.3, 1.1)
        station.add(desk)

        figure = makeOfficer()
        figure.position.set(0, 0.3, 0)
        station.add(figure)
      } else {
        const desk = makeDesk(accentMat)
        desk.position.set(0, 0, 1.1)
        station.add(desk)
        const chair = makeChair()
        chair.position.set(0, 0, -0.2)
        station.add(chair)
        if (def.kind === 'writer') {
          figure = makeResearcher({ writing: true })
          // 文稿 + 笔
          const paper = new THREE.Mesh(new THREE.PlaneGeometry(0.55, 0.4), MAT.paper)
          paper.rotation.x = -Math.PI / 2
          paper.position.set(0.3, 1.125, 1.82)
          const pen = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.18, 8), MAT.dark)
          pen.rotation.x = 1.1
          pen.position.set(0.3, 1.2, 1.72)
          station.add(paper, pen)
        } else {
          figure = makeResearcher()
          const monitor = makeMonitor(accentMat)
          monitor.position.set(0, 0, 2.05)
          station.add(monitor)
        }
        station.add(figure)
      }

      // 状态信标（席位上方的全息标记）
      const beaconY = def.kind === 'officer' ? 3.6 : 2.9
      const beacon = new THREE.Mesh(new THREE.IcosahedronGeometry(0.26, 0), accentMat)
      beacon.position.y = beaconY
      station.add(beacon)
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.5, 0.03, 10, 40), accentMat)
      ring.rotation.x = Math.PI / 2.4
      ring.position.y = beaconY
      station.add(ring)

      const label = makeLabel(def.label)
      label.position.y = beaconY + 0.75
      station.add(label)

      // 席位台灯（照亮人物与桌面）
      const lamp = new THREE.PointLight(0xffe0b3, def.kind === 'officer' ? 22 : 10, 7)
      lamp.position.set(0, beaconY - 0.4, 1.2)
      station.add(lamp)

      // 全部网格纳入双击拾取
      station.traverse((obj) => {
        if (obj.isMesh) {
          obj.userData.agentId = def.id
          this.clickables.push(obj)
        }
      })

      this.scene.add(station)
      this.nodes[def.id] = {
        def, group: station, figure, accentMat, beacon, ring, status: 'idle',
        figureBaseY: figure.position.y,
      }
    }
  }

  _buildLinks() {
    const from = new THREE.Vector3(0, 2.4, -8)
    for (const id of ['lightning', 'wind', 'icing', 'bird', 'audit']) {
      const p = this.nodes[id].group.position
      const to = new THREE.Vector3(p.x, 2.2, p.z)
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([from, to]),
        new THREE.LineBasicMaterial({ color: 0x22d3ee, transparent: true, opacity: 0.22 })
      )
      this.scene.add(line)

      const pulse = new THREE.Mesh(
        new THREE.SphereGeometry(0.15, 12, 12),
        new THREE.MeshBasicMaterial({ color: 0xfbbf24 })
      )
      pulse.add(new THREE.PointLight(0xfbbf24, 4, 4))
      pulse.visible = false
      this.scene.add(pulse)

      this.links[id] = { line, pulse, active: false, t: Math.random(), from, to }
    }
  }

  _bindEvents(container) {
    this.renderer.domElement.addEventListener('dblclick', (e) => {
      const rect = this.renderer.domElement.getBoundingClientRect()
      this.pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
      this.pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1
      this.raycaster.setFromCamera(this.pointer, this.camera)
      const hits = this.raycaster.intersectObjects(this.clickables)
      if (hits.length) {
        const id = hits[0].object.userData.agentId
        this.focusOn(id)
        this.onAgentDblClick?.(id)
      }
    })

    addEventListener('resize', () => {
      this.camera.aspect = container.clientWidth / container.clientHeight
      this.camera.updateProjectionMatrix()
      this.renderer.setSize(container.clientWidth, container.clientHeight)
    })
  }

  focusOn(agentId) {
    const node = this.nodes[agentId]
    if (!node) return
    const p = node.group.position
    const lookAt = new THREE.Vector3(p.x, p.y + 1.6, p.z)
    let camPos
    if (agentId === 'commander') {
      camPos = new THREE.Vector3(p.x, p.y + 3.2, p.z + 8.5)
    } else {
      // 越过席位肩膀看向司令员的视角
      const dir = p.clone().sub(CMD_POS).setY(0).normalize()
      camPos = p.clone().add(dir.multiplyScalar(6.5)).add(new THREE.Vector3(0, 3, 0))
    }
    this.focusTarget = { lookAt, camPos }
  }

  setStatus(agentId, status) {
    const node = this.nodes[agentId]
    if (!node) return
    node.status = status
    const color = STATUS_COLORS[status] || STATUS_COLORS.idle
    node.accentMat.color.setHex(color)
    node.accentMat.emissive.setHex(color)
    if (this.links[agentId]) {
      this.links[agentId].active = status === 'running'
      this.links[agentId].line.material.color.setHex(
        status === 'running' ? 0xfbbf24 : status === 'completed' ? 0x34d399 : 0x22d3ee
      )
    }
  }

  _animate() {
    requestAnimationFrame(() => this._animate())
    const t = this.clock.getElapsedTime()

    let i = 0
    for (const node of Object.values(this.nodes)) {
      // 人物轻微呼吸浮动
      node.figure.position.y = node.figureBaseY + Math.sin(t * 1.8 + i * 1.3) * 0.02
      node.beacon.rotation.y = t * 0.9
      node.ring.rotation.z = t * 1.2
      i++

      if (node.status === 'running') {
        node.accentMat.emissiveIntensity = 1.5 + Math.sin(t * 6) * 0.8
        node.ring.scale.setScalar(1 + Math.sin(t * 4) * 0.12)
      } else if (node.status === 'error') {
        node.accentMat.emissiveIntensity = Math.sin(t * 10) > 0 ? 1.8 : 0.2
      } else if (node.status === 'completed') {
        node.accentMat.emissiveIntensity = 1.1
        node.ring.scale.setScalar(1)
      } else {
        node.accentMat.emissiveIntensity = 0.65 + Math.sin(t * 1.5) * 0.1
        node.ring.scale.setScalar(1)
      }
    }

    for (const link of Object.values(this.links)) {
      if (link.active) {
        link.pulse.visible = true
        link.t = (link.t + 0.012) % 1
        link.pulse.position.lerpVectors(link.from, link.to, link.t)
      } else {
        link.pulse.visible = false
      }
    }

    this.dust.rotation.y = t * 0.006

    if (this.focusTarget) {
      this.camera.position.lerp(this.focusTarget.camPos, 0.045)
      this.controls.target.lerp(this.focusTarget.lookAt, 0.08)
      if (this.camera.position.distanceTo(this.focusTarget.camPos) < 0.15) {
        this.focusTarget = null
      }
    }

    this.controls.update()
    this.renderer.render(this.scene, this.camera)
  }
}
