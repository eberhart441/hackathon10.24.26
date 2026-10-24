import { render } from 'preact';
import '@fontsource/atkinson-hyperlegible/latin-400.css';
import '@fontsource/atkinson-hyperlegible/latin-700.css';
import './styles.css';
import { App } from './ui/App';

render(<App />, document.getElementById('root')!);
