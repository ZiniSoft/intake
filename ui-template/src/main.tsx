import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App } from './app/App'
import { StoreProvider } from './app/store'
import { applyBrand } from './brand'
import { I18nProvider } from './i18n'
import './tokens.css'
import './base.css'
import './ui/ui.css'
import './shell/shell.css'
import './gallery/gallery.css'
import './pages/pages.css'

applyBrand()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <I18nProvider>
      <StoreProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </StoreProvider>
    </I18nProvider>
  </React.StrictMode>,
)
