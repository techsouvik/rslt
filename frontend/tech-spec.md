# UGC Studio AI — Technical Specification

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `react` | ^19.0 | UI framework |
| `react-dom` | ^19.0 | React DOM renderer |
| `vite` | ^6.0 | Build tool |
| `@vitejs/plugin-react` | ^4.0 | Vite React integration |
| `typescript` | ^5.7 | Type safety |
| `tailwindcss` | ^4.0 | Utility CSS |
| `@tailwindcss/vite` | ^4.0 | Tailwind Vite plugin |
| `three` | ^0.172 | WebGL blob background |
| `meshline` | ^3.3 | Glowing trajectory lines |
| `gsap` | ^3.12 | State transition animations, number counters |
| `lucide-react` | ^0.468 | All iconography |
| `@fontsource/inter` | ^5.0 | Inter font (weights 400, 500, 600, 700) |
| `@fontsource/jetbrains-mono` | ^5.0 | JetBrains Mono font |

## Component Inventory

### Layout Shell (persistent across all states)

| Component | Source | Notes |
|-----------|--------|-------|
| `Sidebar` | Custom | Fixed 260px left panel. Glassmorphism. Contains brand, nav, conversations, bottom actions. Collapsible on mobile via hamburger. |
| `BottomInputBar` | Custom | Floating pill-shaped input bar fixed to bottom. Glassmorphism. Text input + icon buttons + send button. |
| `BackgroundCanvas` | Custom | Full-viewport WebGL scene (Three.js). Morphing blob + MeshLine trajectories. Falls back to Canvas 2D gradient on low-power devices. |
| `GlassPanel` | Custom | Reusable glassmorphism container. Props: `variant` ('light' \| 'standard' \| 'heavy'), `borderRadius`, `padding`, `shadow`. Used across all three states. |

### Screen States (mutually exclusive, animated transitions)

| Component | Source | Notes |
|-----------|--------|-------|
| `WelcomeScreen` | Custom | Hero headline, subtitle, 3 prompt suggestion cards. Full main area, vertically centered. |
| `GeneratingScreen` | Custom | Agent workflow panel with step list, progress bar, agent cards. Max-width 640px centered. |
| `ResultScreen` | Custom | Video player, stats row, action buttons. Full-width, max 960px centered. |

### Reusable Components

| Component | Source | Used By |
|-----------|--------|---------|
| `PromptCard` | Custom | WelcomeScreen — glass card with icon, title, description. Hover lift + scale. |
| `AgentStep` | Custom | GeneratingScreen — step row with animated icon (check/spinner), label, status. |
| `AgentCard` | Custom | GeneratingScreen — quote card with agent label and italic description. |
| `VideoPlayer` | Custom | ResultScreen — 16:9 player with overlay controls, play/pause toggle, progress bar, fullscreen, volume. |
| `StatCounter` | Custom | ResultScreen — animated number counter (GSAP-driven). Props: `value`, `suffix`, `label`, `subtitle`. |
| `ActionPill` | Custom | ResultScreen — pill-shaped glass button with icon. Hover brighten + shadow. |

## Animation Implementation

| Animation | Library | Approach | Complexity |
|-----------|---------|----------|------------|
| **WebGL blob background** | Three.js raw (ShaderMaterial + IcosahedronGeometry) + MeshLine | Custom vertex/fragment shaders with raymarched SDF blob. 8 orbiting MeshLine trajectories. Mouse-reactive uniform lerping. See design.md for full shader code. | **High** 🔒 |
| **Welcome → Generating transition** | GSAP timeline | Choreographed timeline: welcome content fadeOut+translateY, then generating content fadeIn+translateY, then workflow panel scaleIn, then steps staggerIn. | Medium |
| **Generating → Result transition** | GSAP timeline | Timeline: workflow panel fade+scale out, video player scaleIn, stats row fadeIn, stat numbers countUp (800ms, staggered 100ms), action buttons staggerIn. | Medium |
| **Stat number counter** | GSAP `gsap.to()` with `onUpdate` | Animate a proxy object from 0 to target value, render formatted value in onUpdate callback. Format suffix (%/ms/GB/s) per stat. | Low |
| **Step spinner animation** | CSS `@keyframes spin` | Continuous 360° rotation, 1s linear infinite. Pure CSS on the spinner icon. | Low |
| **Prompt card hover** | CSS transitions | translateY(-2px), scale(1.02), border-color change, shadow appear. 200ms ease-out. | Low |
| **Glass panel entrance** | GSAP or CSS | scale(0.95→1) + opacity(0→1). Part of the GSAP transition timelines above. | Low |
| **Input bar focus glow** | CSS transitions | Outer box-shadow transition to primary-glow, border color shift. 200ms ease. | Low |
| **Mouse-reactive blob tilt** | Three.js uniform lerping | Lerp uMouse uniform 0.08/frame toward normalized mouse position. | Low |
| **Progress bar fill** | CSS transition or GSAP | width transition from 0% to target (e.g., 98%). Part of GeneratingScreen animation. | Low |

## State & Logic Plan

### App State Machine

Simple React state (`useState`) manages three mutually exclusive screen states:

```
Welcome --(submit prompt)--> Generating --(completion timeout)--> Result
   ^                                                            |
   +------------------(click "New Video")-----------------------+
```

- `screen: 'welcome' | 'generating' | 'result'`
- Transition from generating→result is triggered by a 4-second `setTimeout` simulating generation completion
- Each transition triggers a GSAP timeline animation
- A `transitioning` flag prevents input during animation

### Video Player State

Local `useState` within `VideoPlayer`:
- `isPlaying: boolean` — toggles play/pause overlay and icon
- `currentTime: number` — simulated progress (auto-increments when playing)
- `isFullscreen: boolean` — toggles fullscreen class
- `isMuted: boolean` — toggles volume icon

### Background Canvas Architecture

`BackgroundCanvas` runs in its own `useEffect` with full Three.js lifecycle:
- Scene, camera, renderer created on mount
- Blob mesh (IcosahedronGeometry + ShaderMaterial) + 8 MeshLine trajectories
- Mouse position tracked via `mousemove` listener, lerped per frame
- Cleanup disposes all geometries, materials, renderer on unmount
- Uses `ResizeObserver` for canvas sizing
- Exposes no state to parent — fully self-contained visual layer

## Other Key Decisions

### Three.js Raw (not React Three Fiber)

The background is a single self-contained imperative WebGL scene with no React integration needs. Raw Three.js in a `useEffect` is simpler than R3F's declarative model for this case — no need for the `@react-three/fiber` + `@react-three/drei` overhead.

### Canvas 2D Fallback

Detect low-power devices via `navigator.hardwareConcurrency < 4` or `matchMedia('(prefers-reduced-motion: reduce)')`. Swap the WebGL scene for the Canvas 2D organic gradient described in the design.md. Both are implemented as separate components selected at runtime.

### No Routing

Single-screen experience with state-driven transitions. No `react-router` needed. The URL does not change between states.

### shadcn/ui — Not Used

The design's glassmorphism aesthetic and custom component shapes don't align with shadcn's default styling. All components are custom-built with Tailwind utility classes for precise control over glass effects (backdrop-filter, semi-transparent backgrounds, inner glows). The component count is small enough that custom implementation is more efficient than shimming shadcn.

### Font Loading Strategy

Use `@fontsource/inter` and `@fontsource/jetbrains-mono` npm packages (imported in main.tsx) instead of Google Fonts CDN. Better for offline development and Vite bundling. No `font-display: swap` needed — @fontsource handles this.
