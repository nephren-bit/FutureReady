import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { ThemeProvider } from './contexts/ThemeContext'
import Navbar from './components/layout/Navbar'
import Footer from './components/layout/Footer'
import Landing from './pages/Landing'
import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import SelfPractice from './pages/SelfPractice'
import SessionReview from './pages/SessionReview'
import AdminUsers from './pages/AdminUsers'
import AdminQuality from './pages/AdminQuality'
import PeerReview from './pages/PeerReview'

// Every /app/* route requires an account (Nhóm B, Task 13) -- redirect to
// /login and remember where the person was headed so Login.tsx can send
// them straight back after they sign in. /app/admin/* additionally requires
// is_admin -- a non-admin who guesses the URL lands on the dashboard, not
// an error page, matching there being no "apply for admin" flow at all.
function ProtectedApp() {
  const { isAuthenticated, user } = useAuth()
  const location = useLocation()

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return (
    <>
      <Navbar />
      <main className="flex-1">
        <Routes>
          <Route index element={<Dashboard />} />
          <Route path="luyen-tap" element={<SelfPractice />} />
          <Route path="phien/:id" element={<SessionReview />} />
          <Route
            path="admin/users"
            element={user?.is_admin ? <AdminUsers /> : <Navigate to="/app" replace />}
          />
          <Route
            path="admin/quality"
            element={user?.is_admin ? <AdminQuality /> : <Navigate to="/app" replace />}
          />
        </Routes>
      </main>
      <Footer />
    </>
  )
}

// /cham-ho/:token (Nhom C peer review) also requires login -- "B đăng nhập
// hoặc tạo tài khoản tại chỗ" (plan.md) -- but is not nested under /app/*:
// a rater isn't navigating the product's own dashboard, just opening one
// link, so it gets its own guard rather than living inside ProtectedApp.
function RequirePeerReviewAuth() {
  const { isAuthenticated } = useAuth()
  const location = useLocation()

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return (
    <>
      <Navbar />
      <main className="flex-1">
        <PeerReview />
      </main>
      <Footer />
    </>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <div className="min-h-screen flex flex-col bg-bg dark:bg-bg-dark text-text-primary dark:text-text-primary-dark">
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route path="/login" element={<Login />} />
              <Route path="/register" element={<Register />} />
              <Route path="/cham-ho/:token" element={<RequirePeerReviewAuth />} />
              <Route path="/app/*" element={<ProtectedApp />} />
            </Routes>
          </div>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  )
}
