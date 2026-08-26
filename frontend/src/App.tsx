import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Navbar from './components/layout/Navbar'
import Footer from './components/layout/Footer'
import Landing from './pages/Landing'
import Dashboard from './pages/Dashboard'
import SelfPractice from './pages/SelfPractice'
import SessionReview from './pages/SessionReview'

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
                    <Route path="luyen-tap" element={<SelfPractice />} />
                    <Route path="phien/:id" element={<SessionReview />} />
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
