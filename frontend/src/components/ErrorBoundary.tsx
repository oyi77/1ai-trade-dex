import React, { ReactNode, ErrorInfo } from 'react';
import { retryFetch } from '../utils/retryFetch';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

static getDerivedStateFromError(): Partial<State> {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);

    this.setState({
      error,
      errorInfo,
    });

    this.reportErrorToBackend(error, errorInfo);
  }

  private reportErrorToBackend = async (error: Error, errorInfo: ErrorInfo) => {
    try {
      const response = await retryFetch(
        '/api/v1/errors/frontend',
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            message: error.toString(),
            stack: error.stack,
            componentStack: errorInfo.componentStack,
            timestamp: new Date().toISOString(),
            userAgent: navigator.userAgent,
          }),
        },
        { maxAttempts: 1 }
      );

      if (!response.ok) {
        console.error('Failed to report error to backend:', response.statusText);
      }
    } catch (err) {
      console.error('Error reporting to backend:', err);
    }
  };

  private handleReload = () => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-black flex items-center justify-center p-4">
          <div className="bg-neutral-950 border border-neutral-800 shadow-lg p-8 max-w-md w-full">
            <div className="flex items-center justify-center w-12 h-12 mx-auto bg-red-500/10 rounded-full mb-4">
              <svg
                className="w-6 h-6 text-red-600"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 8v4m0 4v.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
            </div>

            <h1 className="text-2xl font-bold text-center text-neutral-900 mb-2">
              Something went wrong
            </h1>

            <p className="text-center text-neutral-600 mb-6">
              An unexpected error occurred. Please try reloading the page.
            </p>

            {this.state.error && (
              <div className="mb-6">
                <p className="text-sm font-semibold text-neutral-700 mb-2">Error Message:</p>
                <p className="text-sm text-neutral-400 bg-neutral-900 p-3 rounded break-words">
                  {this.state.error.toString()}
                </p>
              </div>
            )}

            {import.meta.env.DEV && this.state.errorInfo && (
              <div className="mb-6">
                <p className="text-sm font-semibold text-neutral-700 mb-2">Component Stack:</p>
                <pre className="text-xs text-neutral-400 bg-neutral-900 p-3 rounded overflow-auto max-h-40">
                  {this.state.errorInfo.componentStack}
                </pre>
              </div>
            )}

            <button
              onClick={this.handleReload}
              className="w-full bg-red-600 hover:bg-red-700 text-white font-semibold py-2 px-4 rounded transition-colors"
            >
              Reload Page
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
