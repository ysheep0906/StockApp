import { NavLink, Outlet, useNavigate } from 'react-router'
import { useAuth } from '../auth'

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const linkStyle = ({ isActive }: { isActive: boolean }) => ({
    marginRight: 16,
    fontWeight: isActive ? 'bold' : 'normal',
  })

  async function handleLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div style={{ fontFamily: 'sans-serif' }}>
      <nav
        style={{
          display: 'flex',
          alignItems: 'center',
          padding: '12px 24px',
          borderBottom: '1px solid #ddd',
        }}
      >
        <NavLink to="/" end style={linkStyle}>
          대시보드
        </NavLink>
        <NavLink to="/watchlist" style={linkStyle}>
          관심종목
        </NavLink>
        <span style={{ marginLeft: 'auto' }}>
          {user?.username}{' '}
          <button onClick={() => void handleLogout()}>로그아웃</button>
        </span>
      </nav>
      <Outlet />
    </div>
  )
}