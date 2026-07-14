export default function Footer() {
  return (
    <footer className="border-t border-border dark:border-border-dark py-8">
      <div className="mx-auto flex max-w-6xl flex-col items-center gap-3 px-4 sm:px-6">
        <div className="flex items-center gap-2">
          <span className="text-lg font-semibold text-text-primary dark:text-text-primary-dark">
            EmpathAI
          </span>
          <span className="h-2 w-2 rounded-full bg-accent" />
        </div>
        <p className="text-sm text-text-secondary dark:text-text-secondary-dark">
          Huấn luyện giao tiếp AI-powered
        </p>
        <p className="text-xs text-text-muted dark:text-text-muted-dark">
          &copy; {new Date().getFullYear()} EmpathAI. All rights reserved.
        </p>
      </div>
    </footer>
  )
}
