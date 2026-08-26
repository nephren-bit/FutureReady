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
            Ghi lại buổi thuyết trình hoặc phỏng vấn tự luyện trước webcam.
            Xem lại từng khoảnh khắc máy đo được trên dòng thời gian --
            không chấm điểm, không so sánh với ai khác.
          </motion.p>

          <motion.div
            variants={fadeUp}
            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
            className="mt-8 flex flex-wrap items-center gap-4"
          >
            <Link
              to="/app/luyen-tap"
              className="inline-flex items-center gap-2.5 bg-accent hover:bg-accent-hover text-white font-medium px-6 py-3 rounded-lg transition-colors duration-200"
            >
              Bắt đầu tự luyện
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
            {['MediaPipe Pose', '7 chỉ số chuyển động', 'Không chấm điểm'].map(
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
      icon: VideoCamera,
      title: 'Ghi hình',
      description:
        'Chọn hồ sơ thuyết trình hoặc phỏng vấn, rồi ghi lại buổi tự luyện ngay trước webcam.',
    },
    {
      number: '02',
      icon: ChartBar,
      title: 'Đo lường',
      description:
        'MediaPipe Pose đo bảy chỉ số chuyển động cơ thể theo từng khung hình -- không suy đoán, chỉ đo.',
    },
    {
      number: '03',
      icon: FileText,
      title: 'Xem lại',
      description:
        'Xem dòng thời gian các khoảnh khắc máy phát hiện được, tự ghi chú tại bất kỳ điểm nào bạn muốn nhớ.',
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
      icon: ChartBar,
      title: 'Chỉ số chuyển động cơ thể',
      description:
        'Tỷ lệ ngẩng đầu, độ lắc lư tư thế, tần suất cử chỉ tay, độ nghiêng vai... đo bằng MediaPipe Pose. Không đo được thì báo lý do, không bao giờ trả về số 0 giả.',
      tint: 'bg-accent/[0.04]',
    },
    {
      icon: VideoCamera,
      title: 'Sự kiện phát hiện được',
      description:
        'Cúi đầu kéo dài, đứng yên quá lâu, quay người khỏi camera, khoanh tay... Nhãn chỉ mô tả cái đo được, không bao giờ suy đoán nguyên nhân.',
      tint: 'bg-transparent',
    },
    {
      icon: FileText,
      title: 'Dòng thời gian xem lại',
      description:
        'Video kèm dải mốc sự kiện ngay dưới thanh tiến trình -- bấm vào bất kỳ mốc nào để nhảy thẳng tới khoảnh khắc đó.',
      tint: 'bg-transparent',
    },
    {
      icon: Sparkle,
      title: 'Tự ghi chú',
      description:
        'Thêm ghi chú tại bất kỳ điểm nào trong lúc xem lại, sửa hoặc xoá tự do -- chỉ bạn mới thấy được ghi chú của chính mình.',
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
    'Ghi hình',
    'Trích khung hình',
    'Đo tư thế (Pose)',
    'Phát hiện sự kiện',
    'Xem lại & ghi chú',
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
            Một pipeline đo lường xác định, từ video thô tới dòng thời gian sự kiện -- không có bước chấm điểm nào.
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
              to="/app/luyen-tap"
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
          Tự luyện thuyết trình &amp; phỏng vấn, không chấm điểm.
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
