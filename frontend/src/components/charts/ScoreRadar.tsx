import { RadarChart, PolarGrid, PolarAngleAxis, Radar, ResponsiveContainer } from 'recharts'

const LABEL_MAP: Record<string, string> = {
  resume_score: 'CV',
  slide_content_score: 'Nội dung Slide',
  slide_visual_score: 'Hình ảnh Slide',
  speech_delivery_score: 'Giọng nói',
  transcript_quality_score: 'Chất lượng nội dung',
  body_language_score: 'Ngôn ngữ cơ thể',
  emotional_confidence_score: 'Tự tin cảm xúc',
  presentation_readiness: 'Sẵn sàng thuyết trình',
  interview_readiness: 'Sẵn sàng phỏng vấn',
}

function CustomTick({ x, y, payload }: { x: number; y: number; payload?: { value: string } }) {
  if (!payload) return null
  const label = LABEL_MAP[payload.value] ?? payload.value
  return (
    <text
      x={x}
      y={y}
      textAnchor="middle"
      dominantBaseline="central"
      className="fill-text-secondary text-xs font-medium"
    >
      <tspan x={x} dy="-0.4em">
        {label}
      </tspan>
    </text>
  )
}

export default function ScoreRadar({ scores }: { scores: Record<string, number | null> }) {
  const data = Object.entries(scores)
    .filter(([key, val]) => val !== null && key !== 'overall_score')
    .map(([key, val]) => ({
      subject: key,
      score: val as number,
    }))

  if (data.length === 0) {
    return (
      <div className="flex h-[300px] items-center justify-center text-text-muted">
        Không có dữ liệu điểm số
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={300}>
      <RadarChart data={data} cx="50%" cy="50%" outerRadius="70%">
        <PolarGrid stroke="#e5e5e5" />
        <PolarAngleAxis dataKey="subject" tick={<CustomTick x={0} y={0} />} />
        <Radar
          dataKey="score"
          stroke="#2563eb"
          fill="#3b82f6"
          fillOpacity={0.2}
          strokeWidth={2}
        />
      </RadarChart>
    </ResponsiveContainer>
  )
}
