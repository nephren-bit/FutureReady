import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Navbar from './components/layout/Navbar'
import Footer from './components/layout/Footer'
import { RequireAdmin, RequireAuth } from './components/RequireAuth'
import { AuthProvider } from './lib/auth'
import Landing from './pages/Landing'
import Dashboard from './pages/Dashboard'
import NewSession from './pages/NewSession'
import SessionDetail from './pages/SessionDetail'
import Report from './pages/Report'
import Practice from './pages/Practice'
import Login from './pages/Login'
import Register from './pages/Register'
import Account from './pages/Account'
import Admin from './pages/Admin'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <div className="min-h-screen flex flex-col bg-bg dark:bg-bg-dark text-text-primary dark:text-text-primary-dark">
          <Routes>
            {/* Reachable without an account -- the report's Khach vang lai
                (AC-01) may view the landing page, register, and sign in. */}
            <Route path="/" element={<Landing />} />
            <Route path="/dang-nhap" element={<Login />} />
            <Route path="/dang-ky" element={<Register />} />

            <Route
              path="/app/*"
              element={
                <RequireAuth>
                  <>
                    <Navbar />
                    <main className="flex-1">
                      <Routes>
                        <Route index element={<Dashboard />} />
                        <Route path="new" element={<NewSession />} />
                        <Route path="practice" element={<Practice />} />
                        <Route path="sessions/:id" element={<SessionDetail />} />
                        <Route path="sessions/:id/report" element={<Report />} />
                        <Route path="tai-khoan" element={<Account />} />
                        {/* Guarded again inside the authenticated area: being
                            signed in is not the same as being an administrator. */}
                        <Route
                          path="quan-tri"
                          element={
                            <RequireAdmin>
                              <Admin />
                            </RequireAdmin>
                          }
                        />
                      </Routes>
                    </main>
                    <Footer />
                  </>
                </RequireAuth>
              }
            />
          </Routes>
        </div>
      </AuthProvider>
    </BrowserRouter>
  )
}
