import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import { AuthProvider } from './lib/auth.jsx'
import { SymbolProvider } from './lib/symbol.jsx'
import './index.css'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <SymbolProvider>
          <App />
        </SymbolProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
