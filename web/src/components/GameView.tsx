import type { EnemyTrace, TickTrace } from '../schema/bundle'
import { AIM_BAND_DEG, NEAR_WALL, aimBandHalfWidth, fmt, signed } from '../data/derive'
import type { EpisodeBundle } from '../data/loader'
import { frameUrl } from '../data/loader'
import { useApp } from '../store'

const WALL_SCALE = 300 // distance at which a wall arc reaches full length
const RADAR = { x: 44, y: 232, inner: 10, outer: 50 }

function wallRadius(distance: number): number {
  return RADAR.inner + (RADAR.outer - RADAR.inner) * Math.min(1, Math.max(0, distance) / WALL_SCALE)
}

/** An annular wedge centred on `angle` (degrees, 0 = straight up, negative = left). */
function wedge(angle: number, spread: number, radius: number): string {
  const toXY = (deg: number, r: number) => {
    const rad = ((deg - 90) * Math.PI) / 180
    return [RADAR.x + r * Math.cos(rad), RADAR.y + r * Math.sin(rad)]
  }
  const [x1, y1] = toXY(angle - spread, RADAR.inner)
  const [x2, y2] = toXY(angle - spread, radius)
  const [x3, y3] = toXY(angle + spread, radius)
  const [x4, y4] = toXY(angle + spread, RADAR.inner)
  return `M${x1},${y1} L${x2},${y2} A${radius},${radius} 0 0 1 ${x3},${y3} L${x4},${y4} A${RADAR.inner},${RADAR.inner} 0 0 0 ${x1},${y1} Z`
}

const letter = (i: number) => String.fromCharCode(65 + (i % 26))

function side(angle: number): string {
  if (Math.abs(angle) < 0.5) return 'on the crosshair'
  return `${fmt(Math.abs(angle), 1)}° ${angle > 0 ? 'left' : 'right'} of the crosshair`
}

function describeEnemy(e: EnemyTrace): string {
  const aimed = Math.abs(e.angle_offset) <= AIM_BAND_DEG
  return `${e.name}: ${fmt(e.distance, 0)} units away, ${side(e.angle_offset)}; ${aimed ? 'inside' : 'outside'} the aim band`
}

function Tag({
  x,
  y,
  text,
  color,
  anchorEnd = false,
}: {
  x: number
  y: number
  text: string
  color: string
  anchorEnd?: boolean
}) {
  const w = 9
  const left = anchorEnd ? x - w : x
  const top = anchorEnd ? y - w : y
  return (
    <g>
      <rect x={left} y={top} width={w} height={w} rx={1.5} fill={color} />
      <text
        x={left + w / 2}
        y={top + w - 2}
        fontSize={7.5}
        fontWeight={700}
        fill="#fff"
        textAnchor="middle"
        style={{ stroke: 'none' }}
      >
        {text}
      </text>
    </g>
  )
}

export function GameView({ bundle, tick }: { bundle: EpisodeBundle; tick: TickTrace }) {
  const depth = useApp((s) => s.depth)
  const state = tick.state
  const width = state?.screen_width ?? bundle.meta.frames.width ?? 320
  const height = state?.screen_height ?? bundle.meta.frames.height ?? 240
  const centre = width / 2
  const band = aimBandHalfWidth(width)
  const enemies = state?.enemies ?? []
  const pickups = state?.pickups ?? []
  const nearRing = wallRadius(NEAR_WALL)
  const walls = state?.walls
  return (
    <>
      <div className="frame">
        <img
          src={frameUrl(bundle, tick.tick)}
          alt={`The game screen at tick ${tick.tick}`}
          width={width}
          height={height}
        />
        <svg
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          role="img"
          aria-label="Overlays drawn from the trace"
        >
          <rect x={centre - band} y={0} width={band * 2} height={height} fill="var(--accent)" opacity={0.1} />
          <line
            x1={centre - band}
            x2={centre - band}
            y1={0}
            y2={height}
            stroke="var(--accent)"
            strokeDasharray="3 3"
            strokeWidth={0.8}
            opacity={0.8}
          />
          <line
            x1={centre + band}
            x2={centre + band}
            y1={0}
            y2={height}
            stroke="var(--accent)"
            strokeDasharray="3 3"
            strokeWidth={0.8}
            opacity={0.8}
          />
          <text x={centre} y={11} fontSize={9} fill="var(--accent)" textAnchor="middle">
            aim band ±{AIM_BAND_DEG}°
          </text>
          <path
            d={`M${centre - 5},${height / 2} h10 M${centre},${height / 2 - 5} v10`}
            stroke="#fff"
            strokeWidth={1}
            opacity={0.8}
          />

          {pickups.map((p, i) => {
            const w = Math.max(8, p.width ?? 12)
            const h = Math.max(8, p.height ?? 12)
            return (
              <g key={p.id}>
                <rect
                  x={p.screen_x - w / 2}
                  y={p.screen_y - h / 2}
                  width={w}
                  height={h}
                  fill="none"
                  stroke="var(--pickup)"
                  strokeWidth={1.2}
                  strokeDasharray="3 2"
                />
                <Tag x={p.screen_x + w / 2 + 1} y={p.screen_y + h / 2 + 1} text={letter(i)} color="var(--pickup)" />
                <title>{`${p.name} (${p.category}): ${fmt(p.distance, 0)} units away, ${signed(p.angle_offset, 1)}° from the crosshair`}</title>
              </g>
            )
          })}

          {enemies.map((e, i) => {
            const w = Math.max(6, e.width)
            const h = Math.max(6, e.height)
            const aimed = Math.abs(e.angle_offset) <= AIM_BAND_DEG
            return (
              <g key={e.id}>
                <rect
                  x={e.screen_x - w / 2}
                  y={e.screen_y - h / 2}
                  width={w}
                  height={h}
                  fill="none"
                  stroke="var(--enemy)"
                  strokeWidth={aimed ? 2 : 1.2}
                />
                <Tag
                  x={e.screen_x - w / 2 - 1}
                  y={e.screen_y - h / 2 - 1}
                  text={String(i + 1)}
                  color="var(--enemy)"
                  anchorEnd
                />
                <title>{describeEnemy(e)}</title>
              </g>
            )
          })}

          {walls && (
            <g aria-label="Wall distances">
              <circle cx={RADAR.x} cy={RADAR.y} r={RADAR.outer} fill="rgba(0,0,0,0.45)" />
              {(
                [
                  ['left', -50, walls.left ?? 0],
                  ['ahead', 0, walls.front ?? 0],
                  ['right', 50, walls.right ?? 0],
                ] as const
              ).map(([name, angle, distance]) => (
                <path
                  key={name}
                  d={wedge(angle, 18, wallRadius(distance))}
                  fill={distance <= NEAR_WALL ? 'var(--neg)' : 'var(--navigation)'}
                  opacity={0.85}
                >
                  <title>{`Wall ${name}: ${fmt(distance, 0)} units${distance <= NEAR_WALL ? ', closer than 64: blocking' : ''}`}</title>
                </path>
              ))}
              <circle
                cx={RADAR.x}
                cy={RADAR.y}
                r={nearRing}
                fill="none"
                stroke="#fff"
                strokeDasharray="2 2"
                strokeWidth={0.7}
                opacity={0.8}
              />
              <text x={RADAR.x} y={RADAR.y - RADAR.outer - 3} fontSize={8.5} fill="#fff" textAnchor="middle">
                walls
                {depth === 'formula'
                  ? ` ${fmt(walls.left ?? 0, 0)} · ${fmt(walls.front ?? 0, 0)} · ${fmt(walls.right ?? 0, 0)}`
                  : ''}
              </text>
            </g>
          )}
        </svg>
      </div>
      {(enemies.length > 0 || pickups.length > 0) && (
        <ul className="enemy-list" aria-label="What the labels say">
          {enemies.map((e, i) => (
            <li key={e.id}>
              <span className="tag" style={{ background: 'var(--enemy)' }}>
                {i + 1}
              </span>
              <span>
                {e.name}{' '}
                <span className="muted">
                  {side(e.angle_offset)}, {fmt(e.distance, 0)} units away,{' '}
                  {Math.abs(e.angle_offset) <= AIM_BAND_DEG ? 'inside the aim band' : 'outside the aim band'}
                </span>
              </span>
            </li>
          ))}
          {pickups.map((p, i) => (
            <li key={p.id}>
              <span className="tag" style={{ background: 'var(--pickup)' }}>
                {letter(i)}
              </span>
              <span>
                {p.name}{' '}
                <span className="muted">
                  ({p.category}) {side(p.angle_offset)}, {fmt(p.distance, 0)} units away
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="overlay-legend">
        <span>
          <span className="swatch" style={{ border: '1.5px solid var(--enemy)' }} />
          enemy
        </span>
        <span>
          <span className="swatch" style={{ border: '1.5px dashed var(--pickup)' }} />
          pickup
        </span>
        <span>
          <span className="swatch" style={{ background: 'var(--accent)', opacity: 0.4 }} />
          aim band
        </span>
        <span>
          <span className="swatch" style={{ background: 'var(--navigation)' }} />
          wall distance (red when under {NEAR_WALL})
        </span>
      </div>
      <div className="pressed" aria-label="What the motor pressed after this decision">
        {tick.primitive_steps_executed.map((stepText, i) => (
          <div key={i} title={`Step ${i + 1} of the motor burst`}>
            {stepText.replaceAll('_', ' ').replaceAll('+', ' + ')}
          </div>
        ))}
      </div>
    </>
  )
}
