package com.dsefa.flir;
import java.util.concurrent.atomic.AtomicInteger;
public class LifecycleTest {
    public static void main(String[] args)throws Exception{
        Generation gate=new Generation();int old=gate.current();AtomicInteger calls=new AtomicInteger();
        gate.runIfCurrent(old,calls::incrementAndGet);gate.advance();gate.runIfCurrent(old,calls::incrementAndGet);
        if(calls.get()!=1)throw new AssertionError("Old USB/replay callbacks survived stop/restart");
        gate.runIfCurrent(gate.current(),calls::incrementAndGet);
        if(calls.get()!=2)throw new AssertionError("New session callback not accepted");
        java.util.concurrent.CountDownLatch firstEntered=new java.util.concurrent.CountDownLatch(1),releaseFirst=new java.util.concurrent.CountDownLatch(1),secondEntered=new java.util.concurrent.CountDownLatch(1);
        Thread first=new Thread(()->Generation.serializedUsb(()->{firstEntered.countDown();try{releaseFirst.await();}catch(Exception e){throw new RuntimeException(e);}}));
        Thread second=new Thread(()->Generation.serializedUsb(secondEntered::countDown));
        first.start();firstEntered.await();second.start();
        boolean overlap=secondEntered.await(80,java.util.concurrent.TimeUnit.MILLISECONDS);releaseFirst.countDown();first.join();second.join();
        if(overlap)throw new AssertionError("USB replacement overlapped retiring worker");
        System.out.println("PASS callback generation invalidation / serialized USB lifetime");
    }
}
