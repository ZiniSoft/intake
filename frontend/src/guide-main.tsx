import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { PublicGuidePage } from './guide'
import { LocaleProvider } from './i18n'
import './styles.css'

// Entry of the static guide published on GitHub Pages (FR-UI-18). No API, no session: the same content as /huong-dan.
// The router is only there because the guide module imports Link; the public view renders no Link.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <LocaleProvider>
      <BrowserRouter>
        <PublicGuidePage variant="pages" />
      </BrowserRouter>
    </LocaleProvider>
  </React.StrictMode>,
)
