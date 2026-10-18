import React from "react";
import {AbsoluteFill, Sequence} from "remotion";
import {NineGridIntro5s} from "../nine-grid-intro/NineGridIntro";
import introConfigJson from "../nine-grid-intro/intro-text-config.json";
import {COLD_HOOK_FRAMES, TwoShotColdHook} from "./TwoShotColdHook";

const introConfig = introConfigJson as {durationInFrames: number};

export const OPENING_DURATION_FRAMES = COLD_HOOK_FRAMES + introConfig.durationInFrames;

export const OpeningSequence: React.FC = () => (
  <AbsoluteFill style={{backgroundColor: "black"}}>
    <Sequence durationInFrames={COLD_HOOK_FRAMES}>
      <TwoShotColdHook />
    </Sequence>
    <Sequence from={COLD_HOOK_FRAMES} durationInFrames={introConfig.durationInFrames}>
      <NineGridIntro5s />
    </Sequence>
  </AbsoluteFill>
);
