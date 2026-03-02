'use client';

import { useRef, useEffect } from 'react';
import { Card, CardContent } from '@/components/ui/card';

interface Props {
  data: number[];
  compareData?: number[] | null;
  height?: number;
}

export default function EquityCurveChart({ data, compareData, height = 320 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || data.length < 2) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);

    // Compute bounds across both curves
    let allData = [...data];
    if (compareData?.length) allData = [...allData, ...compareData];
    const min = Math.min(...allData);
    const max = Math.max(...allData);
    const range = max - min || 1;
    const pad = range * 0.08;

    const gridColor = '#1e293b';
    const labelColor = '#6b7280';

    // BG
    ctx.fillStyle = '#0f1219';
    ctx.fillRect(0, 0, w, h);

    // Grid
    const gridLines = 5;
    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 0.5;
    ctx.font = '10px monospace';
    ctx.fillStyle = labelColor;
    for (let i = 0; i <= gridLines; i++) {
      const y = (i / gridLines) * h;
      ctx.beginPath();
      ctx.moveTo(40, y);
      ctx.lineTo(w, y);
      ctx.stroke();
      const val = max + pad - ((i / gridLines) * (range + pad * 2));
      ctx.fillText(val.toFixed(0), 2, y + 4);
    }

    // Draw a line
    const drawLine = (d: number[], color: string, lw: number) => {
      if (d.length < 2) return;
      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth = lw;
      ctx.lineJoin = 'round';
      for (let i = 0; i < d.length; i++) {
        const x = 40 + (i / (d.length - 1)) * (w - 50);
        const y = h - ((d[i] - min + pad) / (range + pad * 2)) * h;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    };

    // Fill under primary curve
    if (data.length >= 2) {
      ctx.beginPath();
      for (let i = 0; i < data.length; i++) {
        const x = 40 + (i / (data.length - 1)) * (w - 50);
        const y = h - ((data[i] - min + pad) / (range + pad * 2)) * h;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.lineTo(40 + (w - 50), h);
      ctx.lineTo(40, h);
      ctx.closePath();
      const gradient = ctx.createLinearGradient(0, 0, 0, h);
      const isProfit = data[data.length - 1] >= data[0];
      gradient.addColorStop(0, isProfit ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)');
      gradient.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = gradient;
      ctx.fill();
    }

    // Draw compare first (dimmer)
    if (compareData?.length) {
      drawLine(compareData, '#6b7280', 1.2);
    }

    // Draw primary
    const primaryColor = data[data.length - 1] >= data[0] ? '#22c55e' : '#ef4444';
    drawLine(data, primaryColor, 2);

    // Initial balance line
    if (data.length > 0) {
      const initY = h - ((data[0] - min + pad) / (range + pad * 2)) * h;
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = '#6b7280';
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      ctx.moveTo(40, initY);
      ctx.lineTo(w, initY);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }, [data, compareData]);

  if (!data || data.length < 2) {
    return (
      <Card className="bg-card-bg border-card-border">
        <CardContent className="p-6 text-center text-muted-foreground">
          No equity data
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-card-bg border-card-border">
      <CardContent className="p-0">
        <canvas
          ref={canvasRef}
          className="rounded-lg w-full"
          style={{ height }} // dynamic height from prop
        />
      </CardContent>
    </Card>
  );
}
