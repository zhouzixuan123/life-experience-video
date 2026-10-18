import React from "react";
import {
  AbsoluteFill,
  Composition,
  Easing,
  Img,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import rawCacheParameters from "./nine-grid-cache-parameters.json";
import rawIntroText from "./intro-text-config.json";
import motionSpec from "./motion-spec.json";

export const NINE_GRID_INTRO_WIDTH = 1920;
export const NINE_GRID_INTRO_HEIGHT = 1080;
export const NINE_GRID_INTRO_FPS = motionSpec.fps;
export const NINE_GRID_INTRO_VISUAL_BASE_FRAMES = motionSpec.visualBaseFrames;
const TEMPLATE_SOURCE_FPS = motionSpec.sourceFps;

const SOURCE_DURATION_IN_FRAMES = motionSpec.sourceDurationFrames;
const EFFECT_FRAMES = motionSpec.effectFrames;

type KeyframeSegment = {
  temporal_bezier: number[];
  times: number[];
  values: number[][];
};

type CacheGroup = {
  active: number[];
  position_keyframes: KeyframeSegment[];
};

type CacheParameters = {
  groups: Record<string, CacheGroup>;
  layer_keyframes: Record<string, KeyframeSegment[]>;
};

type TrackSpec = {
  src: string;
  startFrame: number;
};

type RegionSpec = {
  group: string;
  clipPath: string;
};

type TextSegment = {text: string; color: "yellow" | "red" | "white"};
type IntroTextConfig = {
  schemaVersion: number;
  fps: number;
  durationInFrames: number;
  visualBaseFrames: number;
  guideText: string;
  guideStartFrame: number;
  guideEndFrame: number;
  topicRevealFrame: number;
  topicLines: TextSegment[][];
};

const CACHE = rawCacheParameters as unknown as CacheParameters;
const INTRO_TEXT = rawIntroText as IntroTextConfig;

// Four moving layers and a topic still share the installed motion specification.
const TRACKS: TrackSpec[] = motionSpec.previewSourceStarts.map(
  (startFrame, index) => ({
    src: `assets/intro-slot-${String(index + 1).padStart(2, "0")}.png`,
    startFrame,
  }),
);
TRACKS.push({src: "assets/intro-slot-10.png", startFrame: motionSpec.topicSourceStart});

// The tiny overlaps and gaps reproduce the original wipe boundaries.
const REGIONS: RegionSpec[] = [
  {group: "190", clipPath: "inset(33.4% 66.6% 33.2% 0%)"},
  {group: "191", clipPath: "inset(33.4% 33.4% 33.2% 33.2%)"},
  {group: "192", clipPath: "inset(66.8% 0% 0% 66.8%)"},
  {group: "193", clipPath: "inset(66.8% 33.4% 0% 33.2%)"},
  {group: "194", clipPath: "inset(0% 0% 66.6% 66.8%)"},
  {group: "195", clipPath: "inset(66.8% 66.6% 0% 0%)"},
  {group: "196", clipPath: "inset(33.4% 0% 33.2% 66.8%)"},
  {group: "197", clipPath: "inset(0% 33.4% 66.6% 33.2%)"},
  {group: "198", clipPath: "inset(0% 66.6% 66.6% 0%)"},
];

const bezierForDimension = (values: number[], dimension: number) => {
  if (values.length === 4) {
    return values;
  }
  const dimensions = values.length / 4;
  return [
    values[dimension],
    values[dimensions + dimension],
    values[dimensions * 2 + dimension],
    values[dimensions * 3 + dimension],
  ];
};

const evaluateKeyframes = (
  segments: KeyframeSegment[],
  time: number,
  dimension: number,
) => {
  if (segments.length === 0) {
    return 0.5;
  }
  if (time <= segments[0].times[0]) {
    return segments[0].values[0][dimension];
  }
  const last = segments[segments.length - 1];
  if (time >= last.times[1]) {
    return last.values[1][dimension];
  }
  const segment =
    segments.find((candidate) => time <= candidate.times[1]) ?? last;
  const [start, end] = segment.times;
  const progress = Math.max(0, Math.min(1, (time - start) / (end - start)));
  const bezier = bezierForDimension(segment.temporal_bezier, dimension);
  const eased = Easing.bezier(bezier[0], bezier[1], bezier[2], bezier[3])(
    progress,
  );
  const from = segment.values[0][dimension];
  const to = segment.values[1][dimension];
  return from + (to - from) * eased;
};

const getGroupPosition = (group: CacheGroup, time: number) => {
  if (group.position_keyframes.length === 0) {
    return [0.5, 0.5];
  }
  return [
    evaluateKeyframes(group.position_keyframes, time, 0),
    evaluateKeyframes(group.position_keyframes, time, 1),
  ];
};

const normalizedToPixels = (position: number[]) => ({
  x: (position[0] - 0.5) * NINE_GRID_INTRO_WIDTH,
  y: (0.5 - position[1]) * NINE_GRID_INTRO_HEIGHT,
});

const CroppedTile: React.FC<{
  src: string;
  clipPath: string;
  x: number;
  y: number;
  opacity?: number;
}> = ({src, clipPath, x, y, opacity = 1}) => (
  <AbsoluteFill style={{clipPath, translate: `${x}px ${y}px`, opacity}}>
    <Img
      src={staticFile(src)}
      style={{
        width: NINE_GRID_INTRO_WIDTH,
        height: NINE_GRID_INTRO_HEIGHT,
        maxWidth: "none",
      }}
    />
  </AbsoluteFill>
);

const MovingRegion: React.FC<{
  src: string;
  region: RegionSpec;
  localTime: number;
  sourceFrameStep: number;
}> = ({src, region, localTime, sourceFrameStep}) => {
  const group = CACHE.groups[region.group];
  if (localTime < group.active[0]) {
    return null;
  }

  const current = getGroupPosition(group, localTime);
  const previous = getGroupPosition(
    group,
    Math.max(0, localTime - sourceFrameStep / TEMPLATE_SOURCE_FPS),
  );
  const deltaX = current[0] - previous[0];
  const deltaY = current[1] - previous[1];
  const isMoving = Math.hypot(deltaX, deltaY) > 0.0002;
  const ghostWeights = isMoving ? [0.75, 0.875, 1.125, 1.25] : [];
  const currentPixels = normalizedToPixels(current);

  return (
    <>
      {ghostWeights.map((weight) => {
        const pixels = normalizedToPixels([
          previous[0] + deltaX * weight,
          previous[1] + deltaY * weight,
        ]);
        return (
          <CroppedTile
            key={weight}
            src={src}
            clipPath={region.clipPath}
            x={pixels.x}
            y={pixels.y}
            opacity={0.1}
          />
        );
      })}
      <CroppedTile
        src={src}
        clipPath={region.clipPath}
        x={currentPixels.x}
        y={currentPixels.y}
      />
    </>
  );
};

const SilhouetteGrid: React.FC<{localTime: number}> = ({localTime}) => (
  <AbsoluteFill>
    {REGIONS.map((region) => {
      const group = CACHE.groups[region.group];
      if (localTime < group.active[0]) {
        return null;
      }
      const pixels = normalizedToPixels(getGroupPosition(group, localTime));
      return (
        <AbsoluteFill
          key={region.group}
          style={{
            backgroundColor: "#393939",
            clipPath: region.clipPath,
            translate: `${pixels.x}px ${pixels.y}px`,
          }}
        />
      );
    })}
  </AbsoluteFill>
);

const CacheGridEffect: React.FC<{
  src: string;
  localFrame: number;
  sourceFrameStep: number;
}> = ({src, localFrame, sourceFrameStep}) => {
  const localTime = localFrame / TEMPLATE_SOURCE_FPS;
  const layer = CACHE.layer_keyframes;
  const positionSegments =
    layer["LumiLayer_212-trs-blend#p0_position#vector"];
  const scaleSegments = layer["LumiLayer_212-trs-blend#p0_scale#vector"];
  const rotationSegments =
    layer["LumiLayer_212-trs-blend#p0_rotation#number"];
  const positionX = evaluateKeyframes(positionSegments, localTime, 0);
  const positionY = evaluateKeyframes(positionSegments, localTime, 1);
  const scale = evaluateKeyframes(scaleSegments, localTime, 0) / 100;
  const rotation = evaluateKeyframes(rotationSegments, localTime, 0);
  const translateX =
    ((positionX - 290) / 580) * NINE_GRID_INTRO_WIDTH;
  const translateY =
    ((positionY - 290) / 580) * NINE_GRID_INTRO_HEIGHT;

  return (
    <AbsoluteFill
      style={{
        transformOrigin: "center center",
        translate: `${translateX}px ${translateY}px`,
        scale,
        rotate: `${rotation}deg`,
      }}
    >
      <AbsoluteFill
        style={{
          translate: `${(8 / 580) * NINE_GRID_INTRO_WIDTH}px ${(2 / 580) * NINE_GRID_INTRO_HEIGHT}px`,
          filter: "blur(28px)",
          opacity: 0.76,
        }}
      >
        <SilhouetteGrid localTime={localTime} />
      </AbsoluteFill>
      {REGIONS.map((region) => (
        <MovingRegion
          key={region.group}
          src={src}
          region={region}
          localTime={localTime}
          sourceFrameStep={sourceFrameStep}
        />
      ))}
    </AbsoluteFill>
  );
};

const ImageTrack: React.FC<{
  spec: TrackSpec;
  sourceFrame: number;
  sourceFrameStep: number;
}> = ({spec, sourceFrame, sourceFrameStep}) => {
  const localFrame = sourceFrame - spec.startFrame;
  if (localFrame < 0) {
    return null;
  }
  if (localFrame >= EFFECT_FRAMES) {
    return (
      <Img
        src={staticFile(spec.src)}
        style={{
          position: "absolute",
          inset: 0,
          width: NINE_GRID_INTRO_WIDTH,
          height: NINE_GRID_INTRO_HEIGHT,
          maxWidth: "none",
        }}
      />
    );
  }
  return (
    <CacheGridEffect
      src={spec.src}
      localFrame={localFrame}
      sourceFrameStep={sourceFrameStep}
    />
  );
};

const ReplicaTimeline: React.FC<{
  sourceFrame: number;
  sourceFrameStep: number;
}> = ({sourceFrame, sourceFrameStep}) => (
  <AbsoluteFill style={{backgroundColor: "#000", overflow: "hidden"}}>
    {TRACKS.map((spec) => (
      <ImageTrack
        key={spec.src}
        spec={spec}
        sourceFrame={sourceFrame}
        sourceFrameStep={sourceFrameStep}
      />
    ))}
  </AbsoluteFill>
);

const IntroTypography: React.FC = () => {
  const outputFrame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const frame = (outputFrame * INTRO_TEXT.fps) / fps;
  const showGuide =
    frame >= INTRO_TEXT.guideStartFrame && frame < INTRO_TEXT.guideEndFrame;
  const showTopic = frame >= INTRO_TEXT.topicRevealFrame;
  const colors = {yellow: "#ffd83d", red: "#ef2929", white: "#ffffff"};
  return (
    <AbsoluteFill style={{pointerEvents: "none"}}>
      {showGuide ? (
        <div
          style={{
            position: "absolute",
            left: 120,
            right: 120,
            bottom: 54,
            textAlign: "center",
            color: "white",
            fontFamily: '"Microsoft YaHei", "Noto Sans CJK SC", "Source Han Sans SC", "PingFang SC", sans-serif',
            fontWeight: 900,
            fontSize: 54,
            WebkitTextStroke: "4px #111",
            paintOrder: "stroke fill",
            textShadow: "0 5px 8px rgba(0,0,0,.65)",
          }}
        >
          {INTRO_TEXT.guideText}
        </div>
      ) : null}
      {showTopic ? (
        <div
          style={{
            position: "absolute",
            left: "50%",
            right: 90,
            top: "30%",
            textAlign: "center",
            fontFamily: '"Microsoft YaHei", "Noto Sans CJK SC", "Source Han Sans SC", "PingFang SC", sans-serif',
            fontWeight: 900,
            fontSize: 88,
            lineHeight: 1.22,
            WebkitTextStroke: "7px #0b0b0b",
            paintOrder: "stroke fill",
            textShadow: "0 7px 10px rgba(0,0,0,.62)",
          }}
        >
          {INTRO_TEXT.topicLines.map((line, lineIndex) => (
            <div key={lineIndex}>
              {line.map((segment, segmentIndex) => (
                <span key={segmentIndex} style={{color: colors[segment.color]}}>
                  {segment.text}
                </span>
              ))}
            </div>
          ))}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

export const NineGridIntro5s: React.FC = () => {
  const outputFrame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const configFrame = (outputFrame * INTRO_TEXT.fps) / fps;
  const baseFrame = (configFrame * TEMPLATE_SOURCE_FPS) / INTRO_TEXT.fps;
  const sourceFrameStep =
    SOURCE_DURATION_IN_FRAMES / INTRO_TEXT.visualBaseFrames;
  return (
    <AbsoluteFill>
      <ReplicaTimeline
        sourceFrame={baseFrame * sourceFrameStep}
        sourceFrameStep={sourceFrameStep}
      />
      <IntroTypography />
    </AbsoluteFill>
  );
};

export const NineGridIntroComposition: React.FC = () => (
  <Composition
    id="NineGridIntro5s"
    component={NineGridIntro5s}
    durationInFrames={INTRO_TEXT.durationInFrames}
    fps={NINE_GRID_INTRO_FPS}
    width={NINE_GRID_INTRO_WIDTH}
    height={NINE_GRID_INTRO_HEIGHT}
  />
);
