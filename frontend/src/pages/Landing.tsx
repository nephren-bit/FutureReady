import { Link } from 'react-router-dom'
import { motion } from 'motion/react'
import {
  FileText,
  ChartBar,
  VideoCamera,
  Sparkle,
  ArrowRight,
} from '@phosphor-icons/react'

const fadeUp = {
  hidden: { opacity: 0, y: 24 },
  visible: { opacity: 1, y: 0 },
}

const stagger = {
  visible: {
    transition: { staggerChildren: 0.1 },
  },
}

function Hero() {
  return (
    <section className="relative pt-24 pb-20 md:pt-32 md:pb-28">
      <div className="max-w-6xl mx-auto px-6">
        <motion.div
          initial="hidden"
          animate="visible"
          variants={stagger}
          className="max-w-3xl"
        >
          <motion.h1
            variants={fadeUp}
            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
            className="text-4xl md:text-5xl lg:text-6xl font-bold tracking-tighter leading-[1.08] text-text-primary-dark"
          >
            Thành thạo mọi cuộc trò chuyện.
          </motion.h1>

          <motion.p
            variants={fadeUp}
            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
            className="mt-5 text-lg md:text-xl text-text-secondary-dark leading-relaxed max-w-xl"
          >
            Phân tích AI-powered cho CV, slide và bài thuyết trình của bạn.
            Nhận phản hồi có thể hành động trước thời khắc thực sự.
          </motion.p>

          <motion.div
            variants={fadeUp}
            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
            className="mt-8 flex flex-wrap items-center gap-4"
          >
            <Link
              to="/app/new"
              className="inline-flex items-center gap-2.5 bg-accent hover:bg-accent-hover text-white font-medium px-6 py-3 rounded-lg transition-colors duration-200"
            >
              Bắt đầu đánh giá
              <ArrowRight className="w-4 h-4" weight="bold" />
            </Link>
            <Link
              to="/app"
              className="inline-flex items-center gap-2.5 bg-transparent hover:bg-white/5 text-text-primary-dark font-medium px-6 py-3 rounded-lg border border-border-dark transition-colors duration-200"
            >
              Xem bảng điều khiển
            </Link>
          </motion.div>

          <motion.div
            variants={fadeUp}
            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
            className="mt-10 flex flex-wrap gap-3"
          >
            {['6 lớp AI', '30+ trạng thái', 'Phân tích thời gian thực'].map(
              (stat) => (
                <span
                  key={stat}
                  className="inline-flex items-center gap-1.5 text-sm text-text-secondary-dark bg-surface-dark border border-border-dark rounded-full px-4 py-1.5"
                >
                  <Sparkle
                    className="w-3.5 h-3.5 text-accent"
                    weight="fill"
                  />
                  {stat}
                </span>
              ),
            )}
          </motion.div>
        </motion.div>
      </div>
    </section>
  )
}

function HowItWorks() {
  const steps = [
    {
      number: '01',
      icon: FileText,
      title: 'Tải lên',
      description:
        'Tải lên CV, slide hoặc video đã ghi lại thông qua giao diện kéo thả đơn giản.',
    },
    {
      number: '02',
      icon: ChartBar,
      title: 'Phân tích',
      description:
        'Một pipeline AI 6 lớp xử lý từng tài liệu, trích xuất tín hiệu trên nhiều chiều.',
    },
    {
      number: '03',
      icon: VideoCamera,
      title: 'Cải thiện',
      description:
        'Nhận phản hồi có điểm số cùng các mẹo có thể hành động để áp dụng trước buổi phỏng vấn hoặc bài thuyết trình tiếp theo.',
    },
  ]

  return (
    <section className="py-20 md:py-28">
      <div className="max-w-6xl mx-auto px-6">
        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-80px' }}
          variants={stagger}
        >
          <motion.h2
            variants={fadeUp}
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            className="text-3xl md:text-4xl font-bold tracking-tight text-text-primary-dark"
          >
            Cách hoạt động
          </motion.h2>

          <div className="mt-12 grid grid-cols-1 md:grid-cols-3 gap-8 md:gap-6">
            {steps.map((step, i) => (
              <motion.div
                key={step.number}
                variants={fadeUp}
                transition={{
                  duration: 0.5,
                  ease: [0.22, 1, 0.36, 1],
                  delay: i * 0.1,
                }}
                className="relative"
              >
                <div className="flex items-center gap-3 mb-4">
                  <span className="text-sm font-mono text-text-secondary-dark">
                    {step.number}
                  </span>
                  <div className="h-px flex-1 bg-border-dark" />
                </div>
                <div className="w-10 h-10 rounded-lg bg-surface-dark border border-border-dark flex items-center justify-center mb-4">
                  <step.icon className="w-5 h-5 text-accent" weight="regular" />
                </div>
                <h3 className="text-lg font-semibold text-text-primary-dark">
                  {step.title}
                </h3>
                <p className="mt-2 text-sm text-text-secondary-dark leading-relaxed">
                  {step.description}
                </p>
              </motion.div>
            ))}
          </div>
        </motion.div>
      </div>
    </section>
  )
}

function FeaturesGrid() {
  const features = [
    {
      icon: FileText,
      title: 'Phân tích CV',
      description:
        'Chấm điểm mật độ từ khóa, phát hiện động từ hành động, và đánh giá độ hoàn thiện các phần theo tiêu chuẩn ngành.',
      tint: 'bg-accent/[0.04]',
    },
    {
      icon: ChartBar,
      title: 'Trí tuệ Slide',
      description:
        'Mật độ văn bản trên mỗi slide, đánh giá độ phong phú hình ảnh, và chấm điểm sự nhất quán trên toàn bộ bài thuyết trình.',
      tint: 'bg-transparent',
    },
    {
      icon: VideoCamera,
      title: 'Giọng nói & Cách trình bày',
      description:
        'Số từ mỗi phút, theo dõi từ đệm, phân tích độ đa dạng từ vựng, và ước tính trình độ CEFR.',
      tint: 'bg-transparent',
    },
    {
      icon: Sparkle,
      title: 'Cảm xúc & Ngôn ngữ cơ thể',
      description:
        'Dòng thời gian cảm xúc khuôn mặt, đo tỷ lệ giao tiếp bằng mắt, và chấm điểm sự ổn định đầu trong suốt bài trình bày.',
      tint: 'bg-accent/[0.04]',
    },
  ]

  return (
    <section className="py-20 md:py-28">
      <div className="max-w-6xl mx-auto px-6">
        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-80px' }}
          variants={stagger}
        >
          <motion.h2
            variants={fadeUp}
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            className="text-3xl md:text-4xl font-bold tracking-tight text-text-primary-dark"
          >
            Chúng tôi phân tích những gì
          </motion.h2>

          <div className="mt-12 grid grid-cols-1 md:grid-cols-2 gap-4">
            {features.map((feature, i) => (
              <motion.div
                key={feature.title}
                variants={fadeUp}
                transition={{
                  duration: 0.5,
                  ease: [0.22, 1, 0.36, 1],
                  delay: i * 0.08,
                }}
                className={`group rounded-xl border border-border-dark bg-surface-dark p-6 transition-colors duration-200 hover:border-border-dark/80 ${feature.tint}`}
              >
                <div className="w-9 h-9 rounded-lg bg-bg-dark border border-border-dark flex items-center justify-center mb-4">
                  <feature.icon
                    className="w-4.5 h-4.5 text-text-secondary-dark group-hover:text-accent transition-colors duration-200"
                    weight="regular"
                  />
                </div>
                <h3 className="text-base font-semibold text-text-primary-dark">
                  {feature.title}
                </h3>
                <p className="mt-2 text-sm text-text-secondary-dark leading-relaxed">
                  {feature.description}
                </p>
              </motion.div>
            ))}
          </div>
        </motion.div>
      </div>
    </section>
  )
}

function PipelineVisualization() {
  const layers = [
    'Trích xuất',
    'Phân tích',
    'Kết hợp',
    'Chấm điểm',
    'Prompt',
    'Suy luận',
  ]

  return (
    <section className="py-20 md:py-28">
      <div className="max-w-6xl mx-auto px-6">
        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-80px' }}
          variants={stagger}
          className="text-center"
        >
          <motion.h2
            variants={fadeUp}
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            className="text-3xl md:text-4xl font-bold tracking-tight text-text-primary-dark"
          >
            Bên trong hệ thống
          </motion.h2>
          <motion.p
            variants={fadeUp}
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            className="mt-3 text-text-secondary-dark max-w-md mx-auto"
          >
            Một pipeline 6 lớp chuyển đổi từ đầu vào thô thành insight có cấu trúc, có thể hành động.
          </motion.p>

          <motion.div
            variants={fadeUp}
            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
            className="mt-12 flex flex-wrap items-center justify-center gap-3 md:gap-2"
          >
            {layers.map((layer, i) => (
              <div key={layer} className="flex items-center gap-2 md:gap-3">
                <div className="px-4 py-2 rounded-full border border-border-dark bg-surface-dark text-sm font-medium text-text-primary-dark tracking-tight">
                  {layer}
                </div>
                {i < layers.length - 1 && (
                  <svg
                    className="w-5 h-5 text-text-secondary-dark/40 shrink-0"
                    viewBox="0 0 20 20"
                    fill="none"
                  >
                    <path
                      d="M7 5l5 5-5 5"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                )}
              </div>
            ))}
          </motion.div>
        </motion.div>
      </div>
    </section>
  )
}

function CTASection() {
  return (
    <section className="py-20 md:py-28">
      <div className="max-w-6xl mx-auto px-6">
        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-80px' }}
          variants={stagger}
          className="text-center"
        >
          <motion.h2
            variants={fadeUp}
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            className="text-3xl md:text-4xl font-bold tracking-tight text-text-primary-dark"
          >
            Sẵn sàng nâng tầm?
          </motion.h2>
          <motion.div
            variants={fadeUp}
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            className="mt-8"
          >
            <Link
              to="/app/new"
              className="inline-flex items-center gap-2.5 bg-accent hover:bg-accent-hover text-white font-medium px-7 py-3.5 rounded-lg transition-colors duration-200"
            >
              Bắt đầu miễn phí
              <ArrowRight className="w-4 h-4" weight="bold" />
            </Link>
          </motion.div>
        </motion.div>
      </div>
    </section>
  )
}

function LandingFooter() {
  return (
    <footer className="border-t border-border-dark py-10">
      <div className="max-w-6xl mx-auto px-6 flex flex-col md:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <Sparkle className="w-4 h-4 text-accent" weight="fill" />
          <span className="text-sm font-semibold text-text-primary-dark">
            EmpathAI
          </span>
        </div>
        <p className="text-sm text-text-secondary-dark">
          Đào tạo giao tiếp AI-powered.
        </p>
        <p className="text-xs text-text-secondary-dark/60">
          &copy; 2024 EmpathAI
        </p>
      </div>
    </footer>
  )
}

export default function Landing() {
  return (
    <div className="min-h-screen bg-bg-dark">
      <Hero />
      <HowItWorks />
      <FeaturesGrid />
      <PipelineVisualization />
      <CTASection />
      <LandingFooter />
    </div>
  )
}
