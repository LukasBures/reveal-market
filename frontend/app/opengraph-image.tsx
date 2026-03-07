import { ImageResponse } from "next/og";

export const size = {
  width: 1200,
  height: 630,
};

export default function OgImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "flex-start",
          background: "#030712",
          color: "white",
          padding: "80px",
          fontFamily: "Manrope, sans-serif",
        }}
      >
        <div style={{ fontSize: 24, opacity: 0.7, marginBottom: 16 }}>
          REVEAL MARKET
        </div>
        <div style={{ fontSize: 56, fontWeight: 600, lineHeight: 1.1 }}>
          Private prediction markets.
        </div>
        <div style={{ marginTop: 24, fontSize: 28, opacity: 0.8 }}>
          Private while live. Provable at the end.
        </div>
      </div>
    ),
    size
  );
}
