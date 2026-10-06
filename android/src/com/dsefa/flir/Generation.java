package com.dsefa.flir;
public final class Generation {
    private int generation;
    private static final Object USB_LIFETIME=new Object();
    public synchronized int current(){return generation;}
    public synchronized int advance(){return ++generation;}
    public synchronized boolean isCurrent(int token){return token==generation;}
    public synchronized void runIfCurrent(int token,Runnable action){if(token==generation)action.run();}
    public static void serializedUsb(Runnable worker){synchronized(USB_LIFETIME){worker.run();}}
}
