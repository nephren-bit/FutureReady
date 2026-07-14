import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Navbar from './components/layout/Navbar'
import Footer from './components/layout/Footer'
import Landing from './pages/Landing'
import Dashboard from './pages/Dashboard'
import NewSession from './pages/NewSession'
import SessionDetail from './pages/SessionDetail'
import Report from './pages/Report'
import Practice from './pages/Practice'

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen flex flex-col bg-bg dark:bg-bg-dark text-text-primary dark:text-text-primary-dark">
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route
            path="/app/*"
            element={
              <>
                <Navbar />
                <main className="flex-1">
                  <Routes>
                    <Route index element={<Dashboard />} />
                    <Route path="new" element={<NewSession />} />
                    <Route path="practice" element={<Practice />} />
                    <Route path="sessions/:id" element={<SessionDetail />} />
                    <Route path="sessions/:id/report" element={<Report />} />
                  </Routes>
                </main>
                <Footer />
              </>
            }
          />
        </Routes>
      </div>
    </BrowserRouter>
  )
}
