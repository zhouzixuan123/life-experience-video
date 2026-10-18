import React from "react";
import {
  AbsoluteFill,
  Easing,
  Img,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";
import hookConfigJson from "./cold-hook-config.json";

type CaptionColor = "yellow" | "red";
type CaptionBeat = {
  startFrame: number;
  endFrame: number;
  text: string;
  color: CaptionColor;
  fontSize?: number;
};
type HookConfig = {
  fps: number;
  durationInFrames: number;
  postHookPauseFrames: number;
  transitionFrames: number;
  imageSwitchFrames: [number, number];
  imageFocus: [[number, number], [number, number]];
  captionBeats: [CaptionBeat, CaptionBeat, CaptionBeat, CaptionBeat];
  subtitle: {
    position: "staggered_center";
    fontFamily: string;
    fontSize: number;
    strokePx: number;
    upperLeftPx: number;
    upperTopPx: number;
    lowerRightPx: number;
    lowerBottomPx: number;
    shadow: false;
    background: false;
  };
};

const config = hookConfigJson as unknown as HookConfig;
const COLORS: Record<CaptionColor, string> = {
  yellow: "#ffd52b",
  red: "#ff302a",
};

export const COLD_HOOK_FRAMES = config.durationInFrames;

const imageOpacity = (frame: number, index: number): number => {
  const switchFrame = config.imageSwitchFrames[1];
  const start = switchFrame;
  const end = switchFrame + config.transitionFrames;
  return interpolate(
    frame,
    [start, end],
    index === 0 ? [1, 0] : [0, 1],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.inOut(Easing.quad),
    },
  );
};

const HookImage: React.FC<{index: 0 | 1}> = ({index}) => {
  const frame = useCurrentFrame();
  const start = index === 0 ? 0 : config.imageSwitchFrames[1];
  const end = index === 0 ? config.imageSwitchFrames[1] + config.transitionFrames : config.durationInFrames - 1;
  const zoom = interpolate(frame, [start, end], [1, index === 0 ? 1.07 : 1.065], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  const [focusX, focusY] = config.imageFocus[index];
  return (
    <Img
      src={staticFile(`assets/cold-hook-slot-0${index + 1}.png`)}
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        objectFit: "cover",
        opacity: imageOpacity(frame, index),
        transform: `scale(${zoom})`,
        transformOrigin: `${focusX * 100}% ${focusY * 100}%`,
      }}
    />
  );
};

const HookCaptions: React.FC = () => {
  const frame = useCurrentFrame();
  const secondImage = frame >= config.imageSwitchFrames[1];
  const beats = secondImage ? config.captionBeats.slice(2) : config.captionBeats.slice(0, 2);
  const visible = beats.filter((beat) => frame >= beat.startFrame);
  const revealFrames = Math.max(1, Math.round(config.fps * 0.2));

  return (
    <>
      {visible.map((beat, index) => {
        const upperLeft = index === 0;
        const reveal = interpolate(frame, [beat.startFrame, beat.startFrame + revealFrames], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.out(Easing.back(1.25)),
        });
        return (
          <div
            key={`${beat.startFrame}-${beat.text}`}
            style={{
              position: "absolute",
              left: upperLeft ? config.subtitle.upperLeftPx : "auto",
              right: upperLeft ? "auto" : config.subtitle.lowerRightPx,
              top: upperLeft ? config.subtitle.upperTopPx : "auto",
              bottom: upperLeft ? "auto" : config.subtitle.lowerBottomPx,
              maxWidth: 1120,
              color: COLORS[beat.color],
              fontFamily: `${config.subtitle.fontFamily}, sans-serif`,
              fontWeight: 900,
              fontSize: beat.fontSize ?? config.subtitle.fontSize,
              lineHeight: 1.16,
              letterSpacing: 1,
              whiteSpace: "nowrap",
              WebkitTextStroke: `${config.subtitle.strokePx}px #101010`,
              paintOrder: "stroke fill",
              opacity: reveal,
              transform: `translateY(${(1 - reveal) * (upperLeft ? -18 : 18)}px) scale(${0.96 + reveal * 0.04})`,
              transformOrigin: upperLeft ? "left center" : "right center",
            }}
          >
            {beat.text}
          </div>
        );
      })}
    </>
  );
};

export const TwoShotColdHook: React.FC = () => (
  <AbsoluteFill style={{backgroundColor: "#05080d", overflow: "hidden"}}>
    <HookImage index={0} />
    <HookImage index={1} />
    <AbsoluteFill
      style={{background: "linear-gradient(180deg, rgba(2,5,10,.12), rgba(2,5,10,.02) 48%, rgba(2,5,10,.28))"}}
    />
    <HookCaptions />
  </AbsoluteFill>
);
